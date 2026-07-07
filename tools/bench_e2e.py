#!/usr/bin/env python3
"""Bench end-to-end test for the combat robot controller + S3 mock gamepad.

Requires the real robot controller and LilyGo T-Dongle S3 mock controller to be
connected over USB. This is intentionally NOT part of normal pytest; run it
manually after large firmware changes:

    .venv/bin/python tools/bench_e2e.py

What it proves:
  * USB ports are mapped to the expected boards by hardware serial/MAC.
  * Robot serial CLI is alive.
  * S3 mock-gamepad serial CLI is alive.
  * Robot can enter pairing mode and connect to the S3 BLE HID peripheral.
  * S3 report changes propagate through BLE into the robot's parsed
    ControllerState (axes, triggers, buttons, dpad).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

try:
    import serial  # type: ignore
except Exception as exc:  # pragma: no cover - host environment guard
    raise SystemExit(f"pyserial is required: {exc}")

DEFAULT_ROBOT_SERIAL = "28:37:2F:CB:9D:04"
DEFAULT_MOCK_SERIAL = "30:ED:A0:D7:75:F4"
BAUD = 115200


class BenchError(RuntimeError):
    pass


@dataclasses.dataclass
class Ports:
    robot: str
    mock: str


@dataclasses.dataclass
class RobotStatus:
    pairing: str
    connected: bool
    bench: bool
    connected_mac: str
    ly: int
    ry: int
    lt: int
    rt: int
    buttons: int
    dpad: int
    s1_logical: int
    s1_physical_high: int
    s2_logical: int
    s2_physical_high: int
    paired: list[str]


STATUS_RE = re.compile(
    r"CLI STATUS pairing=(?P<pairing>\w+) connected=(?P<connected>[01]) "
    r"bench=(?P<bench>[01]) max_paired=(?P<max_paired>\d+) "
    r"connected_mac=(?P<connected_mac>\S+) "
    r"axes=\{ly:(?P<ly>-?\d+),ry:(?P<ry>-?\d+),lt:(?P<lt>-?\d+),"
    r"rt:(?P<rt>-?\d+),buttons:(?P<buttons>\d+),dpad:(?P<dpad>\d+)\} "
    r"outputs=\{S1:\{logical:(?P<s1_logical>[01]),physical_high:(?P<s1_physical_high>[01])\},"
    r"S2:\{logical:(?P<s2_logical>[01]),physical_high:(?P<s2_physical_high>[01])\}\} "
    r"paired=\[(?P<paired>[^\]]*)\]"
)


def climb_usb_info(tty: str) -> tuple[str | None, str | None, str | None]:
    """Return (vid, pid, serial) for /dev/ttyACM* or /dev/ttyUSB*."""
    name = Path(tty).name
    sys_path = (Path("/sys/class/tty") / name / "device").resolve()
    for p in [sys_path, *sys_path.parents]:
        id_vendor = p / "idVendor"
        id_product = p / "idProduct"
        if id_vendor.exists() and id_product.exists():
            serial_path = p / "serial"
            serial_no = serial_path.read_text().strip() if serial_path.exists() else None
            return id_vendor.read_text().strip(), id_product.read_text().strip(), serial_no
    return None, None, None


def discover_ports(robot_serial: str, mock_serial: str) -> Ports:
    found: dict[str, str] = {}
    for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*"):
        for path in sorted(Path("/dev").glob(Path(pattern).name)):
            tty = str(path)
            _vid, _pid, serial_no = climb_usb_info(tty)
            if serial_no:
                found[serial_no.upper()] = tty
    robot = found.get(robot_serial.upper())
    mock = found.get(mock_serial.upper())
    if not robot or not mock:
        listing = ", ".join(f"{k}->{v}" for k, v in sorted(found.items())) or "none"
        raise BenchError(
            f"Could not find both boards. robot={robot_serial} -> {robot}, "
            f"mock={mock_serial} -> {mock}. Seen: {listing}"
        )
    if robot == mock:
        raise BenchError(f"Robot and mock resolved to the same port: {robot}")
    return Ports(robot=robot, mock=mock)


class SerialCli:
    def __init__(self, port: str, name: str, timeout: float = 0.05):
        self.port = port
        self.name = name
        self.ser = serial.Serial(port, BAUD, timeout=timeout, write_timeout=1)
        time.sleep(0.1)
        self.drain(0.25)

    def close(self) -> None:
        self.ser.close()

    def drain(self, seconds: float = 0.2) -> str:
        end = time.time() + seconds
        data = bytearray()
        while time.time() < end:
            chunk = self.ser.read(4096)
            if chunk:
                data.extend(chunk)
        return data.decode(errors="replace")

    def command(self, cmd: str, seconds: float = 1.0) -> str:
        # Prefix a newline to terminate any stale partial line left by ROM/esptool
        # sync bytes (0x55 / 'U') or monitor attach noise. The device may reply
        # ERR to that junk line; callers search for the response to `cmd`.
        self.ser.write(("\n" + cmd + "\n").encode())
        self.ser.flush()
        return self.drain(seconds)

    def wait_for(self, predicate: Callable[[str], bool], timeout: float, label: str) -> str:
        end = time.time() + timeout
        data = ""
        while time.time() < end:
            chunk = self.ser.read(4096).decode(errors="replace")
            if chunk:
                data += chunk
                if predicate(data):
                    return data
        raise BenchError(f"Timed out waiting for {label} on {self.name}. Tail:\n{data[-2000:]}")


def parse_status(text: str) -> RobotStatus:
    matches = list(STATUS_RE.finditer(text))
    if not matches:
        raise BenchError(f"No CLI STATUS line found in output:\n{text[-2000:]}")
    m = matches[-1]
    paired_raw = m.group("paired").strip()
    paired = [] if not paired_raw else [x.strip() for x in paired_raw.split(",") if x.strip()]
    return RobotStatus(
        pairing=m.group("pairing"),
        connected=m.group("connected") == "1",
        bench=m.group("bench") == "1",
        connected_mac=m.group("connected_mac"),
        ly=int(m.group("ly")),
        ry=int(m.group("ry")),
        lt=int(m.group("lt")),
        rt=int(m.group("rt")),
        buttons=int(m.group("buttons")),
        dpad=int(m.group("dpad")),
        s1_logical=int(m.group("s1_logical")),
        s1_physical_high=int(m.group("s1_physical_high")),
        s2_logical=int(m.group("s2_logical")),
        s2_physical_high=int(m.group("s2_physical_high")),
        paired=paired,
    )


def robot_status(robot: SerialCli) -> RobotStatus:
    out = robot.command("status", seconds=1.0)
    return parse_status(out)


def assert_status_field(robot: SerialCli, label: str, predicate: Callable[[RobotStatus], bool], timeout: float = 5.0) -> RobotStatus:
    end = time.time() + timeout
    last: RobotStatus | None = None
    last_error: Exception | None = None
    while time.time() < end:
        try:
            last = robot_status(robot)
            last_error = None
            if predicate(last):
                print(f"PASS {label}: {last}")
                return last
        except BenchError as exc:
            # Serial CLI output can be interleaved with BLE logs during
            # disconnect/reconnect. Keep polling until timeout instead of
            # failing on a single read that did not include CLI STATUS.
            last_error = exc
        time.sleep(0.25)
    if last_error is not None and last is None:
        raise BenchError(f"FAIL {label}: no parseable status before timeout: {last_error}")
    raise BenchError(f"FAIL {label}: last status={last}")


def expect_mock_ok(mock: SerialCli, cmd: str) -> str:
    out = mock.command(cmd, seconds=0.8)
    if "OK " not in out:
        raise BenchError(f"Mock command {cmd!r} did not return OK. Output:\n{out[-1000:]}")
    print(f"PASS mock {cmd!r}")
    return out


def ensure_connected(robot: SerialCli, timeout: float = 25.0) -> RobotStatus:
    st = robot_status(robot)
    if st.connected and st.connected_mac != "02:00:00:00:be:7c":
        print(f"PASS robot already connected: {st.connected_mac}")
        return st

    if st.connected and st.connected_mac == "02:00:00:00:be:7c":
        print("INFO robot is in API bench-injection state; disconnecting before BLE pairing")
        robot.command("disconnect", seconds=0.8)
        time.sleep(0.5)

    print("INFO robot not connected to real BLE mock; sending pair start")
    out = robot.command("pair start", seconds=2.0)
    if "CLI OK pair start" not in out:
        raise BenchError(f"pair start failed. Output:\n{out[-2000:]}")
    return assert_status_field(
        robot,
        "robot connected to real BLE mock after pair start",
        lambda s: s.connected and s.connected_mac != "02:00:00:00:be:7c",
        timeout=timeout,
    )


class RobotApi:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, query: dict[str, str] | None = None, body: dict | None = None) -> dict:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif method.upper() == "POST":
            data = b""
        req = urllib.request.Request(url, method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                response_body = resp.read().decode(errors="replace")
                if resp.status < 200 or resp.status >= 300:
                    raise BenchError(f"API {method} {url} HTTP {resp.status}: {response_body}")
                try:
                    return json.loads(response_body)
                except json.JSONDecodeError as exc:
                    raise BenchError(f"API {method} {url} returned non-JSON: {response_body!r}") from exc
        except urllib.error.URLError as exc:
            raise BenchError(f"API {method} {url} failed: {exc}") from exc

    def get(self, path: str) -> dict:
        return self.request("GET", path)

    def post(self, path: str, query: dict[str, str] | None = None) -> dict:
        return self.request("POST", path, query=query)

    def post_json(self, path: str, body: dict) -> dict:
        return self.request("POST", path, body=body)


def pack_8bitdo_hex(*, hat: int = 8, lx: int = 127, ly: int = 127, rx: int = 127, ry: int = 127,
                   r2: int = 0, l2: int = 0, b0: int = 0, b1: int = 0) -> str:
    data = [0x01, hat & 0x0F, lx & 0xFF, ly & 0xFF, rx & 0xFF, ry & 0xFF,
            r2 & 0xFF, l2 & 0xFF, b0 & 0xFF, b1 & 0xFF]
    return "".join(f"{b:02x}" for b in data)


def configure_s1_digital(api: RobotApi, *, primary: str, active_high: bool = True,
                         digital_mode: str = "direct", on: int = 1, off: int = 0,
                         preset: str = "direct", custom_pct: int = 50) -> None:
    payload = {
        "S1": {
            "display_name": "Bench S1",
            "direction": "normal",
            "servo_mode": "uni",
            "deadzone": 10,
            "primary": primary,
            "secondary": "NONE",
            "purpose": "digital_output",
            "protocol": "gpio",
            "semantics": "digital_output",
            "active_high": active_high,
            "default_state": False,
            "digital_mode": digital_mode,
            "digital_preset": preset,
            "digital_on_threshold": on,
            "digital_off_threshold": off,
            "digital_custom_pct": custom_pct,
            "power_good": "default",
            "power_warn": "default",
            "power_low": "default",
        }
    }
    resp = api.post_json("/api/config", payload)
    if resp.get("ok") is not True:
        raise BenchError(f"API config S1 digital patch failed: {resp}")


def configure_s2_esc_arming(api: RobotApi) -> None:
    payload = {
        "S2": {
            "display_name": "Bench ESC",
            "direction": "normal",
            "servo_mode": "uni",
            "deadzone": 10,
            "primary": "RT",
            "secondary": "NONE",
            "purpose": "esc",
            "protocol": "oneshot125",
            "semantics": "esc_forward_only",
            "weapon_safety": True,
            "failsafe": "safe_state",
            "weapon_mode": "deadman_only",
            "deadman_source": "A",
            "esc_arm_mode": "hold_source",
            "esc_arm_source": "B",
            "esc_arm_hold_ms": 1500,
            "esc_arm_low_us": 125,
            "esc_arm_high_us": 250,
            "esc_arm_low_ms": 500,
            "esc_arm_high_ms": 500,
            "esc_arm_final_low_ms": 500,
            "min_pulse_us": 125,
            "center_pulse_us": 188,
            "max_pulse_us": 250,
            "frame_hz": 2000,
            "neutral_deadzone": 2,
            "power_good": "default",
            "power_warn": "default",
            "power_low": "disable",
        }
    }
    resp = api.post_json("/api/config", payload)
    if resp.get("ok") is not True:
        raise BenchError(f"API config S2 ESC arming patch failed: {resp}")
    cfg = api.get("/api/config")
    s2 = cfg.get("outputs", {}).get("S2", {})
    arm = s2.get("esc_arm", {})
    if s2.get("purpose") != "esc" or s2.get("protocol") != "oneshot125" or arm.get("mode") != "hold_source":
        raise BenchError(f"API config S2 ESC arming echo mismatch: {s2}")
    if arm.get("source") != "B" or arm.get("hold_ms") != 1500 or arm.get("low_us") != 125 or arm.get("high_us") != 250:
        raise BenchError(f"API config S2 ESC arming sequence echo mismatch: {arm}")
    print("PASS API accepts S2 ESC hold-to-arm sequence config")


def restore_s1_servo(api: RobotApi) -> None:
    resp = api.post_json("/api/config", {
        "S1": {
            "display_name": "Servo 1",
            "direction": "normal",
            "servo_mode": "bi",
            "deadzone": 10,
            "primary": "NONE",
            "secondary": "NONE",
            "purpose": "servo",
            "protocol": "rc_servo_pwm",
            "semantics": "position_servo",
            "active_high": True,
            "default_state": False,
            "digital_mode": "direct",
            "digital_preset": "direct",
            "digital_on_threshold": 1,
            "digital_off_threshold": 0,
            "digital_custom_pct": 50,
            "power_good": "default",
            "power_warn": "default",
            "power_low": "default",
        }
    })
    if resp.get("ok") is not True:
        raise BenchError(f"API restore S1 servo failed: {resp}")


def restore_s2_servo(api: RobotApi) -> None:
    resp = api.post_json("/api/config", {
        "S2": {
            "display_name": "Servo 2",
            "direction": "normal",
            "servo_mode": "bi",
            "deadzone": 10,
            "primary": "NONE",
            "secondary": "NONE",
            "purpose": "servo",
            "protocol": "rc_servo_pwm",
            "semantics": "position_servo",
            "weapon_safety": False,
            "failsafe": "safe_state",
            "weapon_mode": "arming_and_deadman",
            "arming_source": "NONE",
            "deadman_source": "NONE",
            "esc_arm_mode": "manual",
            "esc_arm_source": "NONE",
            "esc_arm_hold_ms": 2000,
            "esc_arm_low_us": 1000,
            "esc_arm_high_us": 2000,
            "esc_arm_low_ms": 1000,
            "esc_arm_high_ms": 1000,
            "esc_arm_final_low_ms": 1000,
            "min_pulse_us": 1000,
            "center_pulse_us": 1500,
            "max_pulse_us": 2000,
            "frame_hz": 50,
            "neutral_deadzone": 5,
            "active_high": True,
            "default_state": False,
            "digital_mode": "direct",
            "digital_preset": "direct",
            "digital_on_threshold": 1,
            "digital_off_threshold": 0,
            "digital_custom_pct": 50,
            "power_good": "default",
            "power_warn": "default",
            "power_low": "default",
        }
    })
    if resp.get("ok") is not True:
        raise BenchError(f"API restore S2 servo failed: {resp}")


def run_api_tests(api: RobotApi, robot: SerialCli, mock: SerialCli) -> None:
    status = api.get("/api/status")
    if status.get("wifi_ap_mode") is not True or status.get("wifi_ip") != "192.168.4.1":
        raise BenchError(f"API status did not report expected AP mode/ip: {status}")
    if "ble_connected" not in status or "pairing_state" not in status:
        raise BenchError(f"API status missing BLE fields: {status}")
    print(f"PASS API /api/status ble_connected={status.get('ble_connected')} pairing={status.get('pairing_state')}")

    bench = api.get("/api/bench/hid/status")
    if bench.get("build_flag") is not True:
        raise BenchError(f"API bench status build_flag was not true: {bench}")
    if bench.get("runtime_enabled") is not True:
        print("INFO API bench runtime flag disabled; enabling it")
        enabled = api.post("/api/bench/hid/enable")
        if enabled.get("ok") is not True:
            raise BenchError(f"API bench enable failed: {enabled}")
    print("PASS API /api/bench/hid/status")

    try:
        api.post_json("/api/config", {"Weapon": {"purpose": "esc", "protocol": "oneshot125", "weapon_safety": True}})
        raise BenchError("obsolete Weapon config patch unexpectedly succeeded")
    except BenchError as exc:
        if "HTTP Error 400" not in str(exc) and "invalid patch" not in str(exc):
            raise
    print("PASS API rejects obsolete top-level Weapon config")

    configure_s2_esc_arming(api)

    # API bench injection directly exercises the WiFi REST path into the robot's
    # HID parser. Firmware bench override suppresses live BLE notifications after
    # injection so the synthetic frame remains observable even if the real mock
    # is still connected. It uses the same 10-byte 8BitDo layout as the S3 mock.
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(b0=0x01)})
    if resp.get("ok") is not True or resp.get("len") != 10:
        raise BenchError(f"API bench hid A injection failed: {resp}")
    assert_status_field(robot, "API bench hid A -> buttons=1", lambda s: s.buttons == 1 and s.connected_mac == "02:00:00:00:be:7c")

    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(ly=0, r2=64, l2=32)})
    if resp.get("ok") is not True or resp.get("len") != 10:
        raise BenchError(f"API bench hid axis/triggers injection failed: {resp}")
    assert_status_field(robot, "API bench hid axis/triggers", lambda s: s.ly == -508 and s.rt == 256 and s.lt == 128)

    configure_s1_digital(api, primary="A", active_high=True)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex()})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench neutral before S1 button test failed: {resp}")
    assert_status_field(robot, "S1 digital BTN_A released -> LOW", lambda s: s.buttons == 0 and s.s1_logical == 0 and s.s1_physical_high == 0)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(b0=0x01)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench A for S1 button test failed: {resp}")
    assert_status_field(robot, "S1 digital BTN_A pressed -> HIGH", lambda s: s.buttons == 1 and s.s1_logical == 1 and s.s1_physical_high == 1)

    configure_s1_digital(api, primary="A", active_high=False)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex()})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench neutral before S1 inverted test failed: {resp}")
    assert_status_field(robot, "S1 inverted BTN_A released -> physical HIGH", lambda s: s.s1_logical == 0 and s.s1_physical_high == 1)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(b0=0x01)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench A for S1 inverted test failed: {resp}")
    assert_status_field(robot, "S1 inverted BTN_A pressed -> physical LOW", lambda s: s.s1_logical == 1 and s.s1_physical_high == 0)

    configure_s1_digital(api, primary="RT", active_high=True, digital_mode="analog_above", on=512, off=448, preset="trigger_half", custom_pct=50)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=64)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench RT=64 for S1 half-press preset test failed: {resp}")
    assert_status_field(robot, "S1 RT half-press preset below threshold", lambda s: s.rt == 256 and s.s1_logical == 0 and s.s1_physical_high == 0)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=128)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench RT=128 for S1 half-press preset test failed: {resp}")
    assert_status_field(robot, "S1 RT half-press preset on", lambda s: s.rt == 512 and s.s1_logical == 1 and s.s1_physical_high == 1)

    configure_s1_digital(api, primary="RT", active_high=True, digital_mode="analog_above", on=600, off=500, preset="custom", custom_pct=59)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=0)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench RT=0 for S1 custom threshold test failed: {resp}")
    assert_status_field(robot, "S1 RT custom threshold off", lambda s: s.rt == 0 and s.s1_logical == 0 and s.s1_physical_high == 0)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=150)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench RT=150 for S1 custom threshold test failed: {resp}")
    assert_status_field(robot, "S1 RT custom threshold on", lambda s: s.rt == 600 and s.s1_logical == 1 and s.s1_physical_high == 1)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=137)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench RT=137 for S1 threshold hold test failed: {resp}")
    assert_status_field(robot, "S1 RT hysteresis holds on", lambda s: s.rt == 548 and s.s1_logical == 1)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=125)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench RT=125 for S1 threshold off test failed: {resp}")
    assert_status_field(robot, "S1 RT hysteresis turns off", lambda s: s.rt == 500 and s.s1_logical == 0 and s.s1_physical_high == 0)

    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex()})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench neutral reset failed: {resp}")
    assert_status_field(robot, "API bench neutral reset", lambda s: s.ly == 0 and s.rt == 0 and s.lt == 0 and s.buttons == 0 and s.dpad == 0)
    restore_s1_servo(api)
    restore_s2_servo(api)

    # Leave the bench in the normal real-BLE state for manual follow-up and for
    # any next test stage.
    robot.command("disconnect", seconds=0.8)
    ensure_connected(robot)


def run(args: argparse.Namespace) -> None:
    ports = Ports(args.robot_port, args.mock_port) if args.robot_port and args.mock_port else discover_ports(
        args.robot_serial, args.mock_serial
    )
    print(f"INFO ports robot={ports.robot} mock={ports.mock}")

    robot = SerialCli(ports.robot, "robot")
    mock = SerialCli(ports.mock, "mock")
    try:
        # CLI liveness.
        if "CLI OK" not in robot.command("help", seconds=1.0):
            raise BenchError("robot CLI help did not respond with CLI OK")
        expect_mock_ok(mock, "PING")

        # Normalize mock state and ensure BLE link.
        expect_mock_ok(mock, "RESET")
        expect_mock_ok(mock, "RATE 30")
        ensure_connected(robot)

        # Centered state should parse to neutral controls.
        expect_mock_ok(mock, "SET LX=127 LY=127 RX=127 RY=127 L2=0 R2=0 HAT=C BTN=")
        assert_status_field(
            robot,
            "centered neutral",
            lambda s: s.connected and s.ly == 0 and s.ry == 0 and s.lt == 0 and s.rt == 0 and s.buttons == 0 and s.dpad == 0,
        )

        # 8BitDo report axis/triggers: robot parser maps (byte - 127) * 4 for axes and trigger*4.
        expect_mock_ok(mock, "SET LY=0")
        assert_status_field(robot, "LY=0 -> -508", lambda s: s.ly == -508)

        expect_mock_ok(mock, "SET LY=255")
        assert_status_field(robot, "LY=255 -> 512", lambda s: s.ly == 512)

        expect_mock_ok(mock, "SET LY=127 L2=255 R2=128")
        assert_status_field(robot, "triggers propagate", lambda s: s.lt == 1020 and s.rt == 512)

        expect_mock_ok(mock, "SET L2=0 R2=0 BTN=A,B,START")
        # A=bit0, B=bit1, START=bit9 -> 1 + 2 + 512 = 515 after robot decode.
        assert_status_field(robot, "buttons A+B+START", lambda s: s.buttons == 515)

        expect_mock_ok(mock, "SET BTN= HAT=N")
        assert_status_field(robot, "hat N -> dpad up", lambda s: s.buttons == 0 and s.dpad == 1)

        expect_mock_ok(mock, "RESET")
        assert_status_field(robot, "reset returns neutral", lambda s: s.ly == 0 and s.rt == 0 and s.buttons == 0 and s.dpad == 0)

        if args.skip_api:
            print("SKIP WiFi API tests (--skip-api)")
        else:
            run_api_tests(RobotApi(args.api_base, timeout=args.api_timeout), robot, mock)

        print("BENCH_E2E PASS")
    finally:
        robot.close()
        mock.close()


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--robot-serial", default=DEFAULT_ROBOT_SERIAL, help="USB serial/MAC shown in sysfs for the robot board")
    p.add_argument("--mock-serial", default=DEFAULT_MOCK_SERIAL, help="USB serial/MAC shown in sysfs for the S3 mock dongle")
    p.add_argument("--robot-port", help="Override robot serial port, e.g. /dev/ttyACM1")
    p.add_argument("--mock-port", help="Override mock serial port, e.g. /dev/ttyACM0")
    p.add_argument("--api-base", default="http://192.168.4.1", help="Robot WiFi API base URL")
    p.add_argument("--api-timeout", type=float, default=5.0, help="HTTP timeout in seconds")
    p.add_argument("--skip-api", action="store_true", help="Skip WiFi/API checks when not connected to the robot AP")
    args = p.parse_args(list(argv) if argv is not None else None)
    try:
        run(args)
        return 0
    except BenchError as exc:
        print(f"BENCH_E2E FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
