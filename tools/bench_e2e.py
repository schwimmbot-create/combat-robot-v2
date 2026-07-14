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
from typing import Any, Callable, Iterable

from drive_sim.assertions import ArcsLeft, ArcsRight, EndsStopped, MovesForward
from drive_sim.board_data import load_board_data
from drive_sim.firmware_runner import TimedStatus, simulate_status_samples
from drive_sim.render import render_report

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
    lx: int
    ly: int
    rx: int
    ry: int
    lt: int
    rt: int
    buttons: int
    dpad: int
    s1_logical: int
    s1_physical_high: int
    s1_pulse_us: int
    s1_duty: int
    s1_arm: str
    s2_logical: int
    s2_physical_high: int
    s2_pulse_us: int
    s2_duty: int
    s2_arm: str
    drive_layout: str
    drive_method: str
    drive_throttle_axis: str
    drive_steering_axis: str
    drive_throttle: int
    drive_steering: int
    drive_left: int
    drive_right: int
    m1_speed: int
    m1_dir: str
    m1_fwd_duty: int
    m1_rev_duty: int
    m1_freq: int
    m2_speed: int
    m2_dir: str
    m2_fwd_duty: int
    m2_rev_duty: int
    m2_freq: int
    paired: list[str]


STATUS_RE = re.compile(
    r"CLI STATUS pairing=(?P<pairing>\w+) connected=(?P<connected>[01]) "
    r"bench=(?P<bench>[01]) max_paired=(?P<max_paired>\d+) "
    r"connected_mac=(?P<connected_mac>\S+) "
    r"axes=\{lx:(?P<lx>-?\d+),ly:(?P<ly>-?\d+),rx:(?P<rx>-?\d+),ry:(?P<ry>-?\d+),"
    r"lt:(?P<lt>-?\d+),rt:(?P<rt>-?\d+),buttons:(?P<buttons>\d+),dpad:(?P<dpad>\d+)\} "
    r"outputs=\{S1:\{logical:(?P<s1_logical>[01]),physical_high:(?P<s1_physical_high>[01]),"
    r"pulse_us:(?P<s1_pulse_us>\d+),duty:(?P<s1_duty>\d+),arm:(?P<s1_arm>\w+)\},"
    r"S2:\{logical:(?P<s2_logical>[01]),physical_high:(?P<s2_physical_high>[01]),"
    r"pulse_us:(?P<s2_pulse_us>\d+),duty:(?P<s2_duty>\d+),arm:(?P<s2_arm>\w+)\}\} "
    r"drive=\{layout:(?P<drive_layout>\w+),method:(?P<drive_method>\w+),"
    r"throttle_axis:(?P<drive_throttle_axis>\w+),steering_axis:(?P<drive_steering_axis>\w+),"
    r"throttle:(?P<drive_throttle>-?\d+),steering:(?P<drive_steering>-?\d+),"
    r"left:(?P<drive_left>-?\d+),right:(?P<drive_right>-?\d+)\} "
    r"motors=\{M1:\{speed:(?P<m1_speed>\d+),dir:(?P<m1_dir>\w+),fwd_duty:(?P<m1_fwd_duty>\d+),rev_duty:(?P<m1_rev_duty>\d+),freq:(?P<m1_freq>\d+)\},"
    r"M2:\{speed:(?P<m2_speed>\d+),dir:(?P<m2_dir>\w+),fwd_duty:(?P<m2_fwd_duty>\d+),rev_duty:(?P<m2_rev_duty>\d+),freq:(?P<m2_freq>\d+)\}\} "
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
        lx=int(m.group("lx")),
        ly=int(m.group("ly")),
        rx=int(m.group("rx")),
        ry=int(m.group("ry")),
        lt=int(m.group("lt")),
        rt=int(m.group("rt")),
        buttons=int(m.group("buttons")),
        dpad=int(m.group("dpad")),
        s1_logical=int(m.group("s1_logical")),
        s1_physical_high=int(m.group("s1_physical_high")),
        s1_pulse_us=int(m.group("s1_pulse_us")),
        s1_duty=int(m.group("s1_duty")),
        s1_arm=m.group("s1_arm"),
        s2_logical=int(m.group("s2_logical")),
        s2_physical_high=int(m.group("s2_physical_high")),
        s2_pulse_us=int(m.group("s2_pulse_us")),
        s2_duty=int(m.group("s2_duty")),
        s2_arm=m.group("s2_arm"),
        drive_layout=m.group("drive_layout"),
        drive_method=m.group("drive_method"),
        drive_throttle_axis=m.group("drive_throttle_axis"),
        drive_steering_axis=m.group("drive_steering_axis"),
        drive_throttle=int(m.group("drive_throttle")),
        drive_steering=int(m.group("drive_steering")),
        drive_left=int(m.group("drive_left")),
        drive_right=int(m.group("drive_right")),
        m1_speed=int(m.group("m1_speed")),
        m1_dir=m.group("m1_dir"),
        m1_fwd_duty=int(m.group("m1_fwd_duty")),
        m1_rev_duty=int(m.group("m1_rev_duty")),
        m1_freq=int(m.group("m1_freq")),
        m2_speed=int(m.group("m2_speed")),
        m2_dir=m.group("m2_dir"),
        m2_fwd_duty=int(m.group("m2_fwd_duty")),
        m2_rev_duty=int(m.group("m2_rev_duty")),
        m2_freq=int(m.group("m2_freq")),
        paired=paired,
    )


def robot_status(robot: SerialCli, seconds: float = 1.0) -> RobotStatus:
    out = robot.command("status", seconds=seconds)
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


def set_bench_battery(api: RobotApi, state: str, pct: int | None = None) -> None:
    query = {"state": state}
    if pct is not None:
        query["pct"] = str(pct)
    resp = api.post("/api/bench/battery", query)
    if resp.get("ok") is not True or resp.get("override") is not True:
        raise BenchError(f"bench battery override {state} failed: {resp}")
    status = api.get("/api/status")
    expected = {"good": 1, "warn": 2, "low": 3}[state]
    if status.get("battery_state") != expected:
        raise BenchError(f"bench battery state echo mismatch for {state}: {status}")
    print(f"PASS bench battery override {state}")


def clear_bench_battery(api: RobotApi) -> None:
    resp = api.post("/api/bench/battery", {"clear": "1"})
    if resp.get("ok") is not True or resp.get("override") is not False:
        raise BenchError(f"bench battery clear failed: {resp}")
    print("PASS bench battery override clear")


def patch_output_power(api: RobotApi, output: str, *, good: str = "default", warn: str = "default", low: str = "default") -> None:
    resp = api.post_json("/api/config", {output: {"power_good": good, "power_warn": warn, "power_low": low}})
    if resp.get("ok") is not True:
        raise BenchError(f"API power patch {output} failed: {resp}")


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


ESC_PROTOCOL_PRESETS = [
    ("rc_esc_pwm", 1000, 1500, 2000, 50),
    ("rc_esc_pwm_100", 1000, 1500, 2000, 100),
    ("rc_esc_pwm_250", 1000, 1500, 2000, 250),
    ("rc_esc_pwm_333", 1000, 1500, 2000, 333),
    ("rc_esc_pwm_490", 1000, 1500, 2000, 490),
    ("oneshot", 1000, 1500, 2000, 490),
    ("oneshot125", 125, 188, 250, 2000),
    ("oneshot42", 42, 63, 84, 4000),
    ("multishot", 5, 15, 25, 8000),
]


def verify_s2_esc_protocol_presets(api: RobotApi, robot: SerialCli) -> None:
    for protocol, min_us, center_us, max_us, frame_hz in ESC_PROTOCOL_PRESETS:
        payload = {
            "S2": {
                "display_name": "Bench Proto",
                "direction": "normal",
                "servo_mode": "uni",
                "deadzone": 10,
                "primary": "RT",
                "secondary": "NONE",
                "purpose": "esc",
                "protocol": protocol,
                "semantics": "esc_forward_only",
                "weapon_safety": False,
                "failsafe": "safe_state",
                "esc_arm_mode": "manual",
                "min_pulse_us": min_us,
                "center_pulse_us": center_us,
                "max_pulse_us": max_us,
                "frame_hz": frame_hz,
                "neutral_deadzone": 2 if max_us <= 250 else 5,
                "esc_arm_low_us": min_us,
                "esc_arm_high_us": max_us,
                "power_good": "default",
                "power_warn": "default",
                "power_low": "default",
            }
        }
        resp = api.post_json("/api/config", payload)
        if resp.get("ok") is not True:
            raise BenchError(f"API config S2 protocol {protocol} failed: {resp}")
        cfg = api.get("/api/config").get("outputs", {}).get("S2", {})
        pulse = cfg.get("pulse", {})
        if cfg.get("protocol") != protocol or pulse.get("min_us") != min_us or pulse.get("max_us") != max_us or pulse.get("frame_hz") != frame_hz:
            raise BenchError(f"API config S2 protocol {protocol} echo mismatch: {cfg}")
        assert_status_field(
            robot,
            f"S2 ESC protocol {protocol} safe pulse",
            lambda s, expected=min_us: s.s2_arm == "manual" and s.s2_pulse_us == expected,
            timeout=3.0,
        )
    print("PASS S2 ESC expanded protocol presets")


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
            "weapon_safety": False,
            "failsafe": "safe_state",
            "weapon_mode": "deadman_only",
            "deadman_source": "A",
            "esc_arm_mode": "hold_source",
            "esc_arm_source": "B",
            "esc_arm_hold_ms": 500,
            "esc_arm_low_us": 125,
            "esc_arm_high_us": 250,
            "esc_arm_low_ms": 1000,
            "esc_arm_high_ms": 1500,
            "esc_arm_final_low_ms": 1000,
            "min_pulse_us": 125,
            "center_pulse_us": 188,
            "max_pulse_us": 250,
            "frame_hz": 2000,
            "neutral_deadzone": 2,
            "power_good": "default",
            "power_warn": "default",
            "power_low": "default",
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
    if arm.get("source") != "B" or arm.get("hold_ms") != 500 or arm.get("low_us") != 125 or arm.get("high_us") != 250:
        raise BenchError(f"API config S2 ESC arming sequence echo mismatch: {arm}")
    print("PASS API accepts S2 ESC hold-to-arm sequence config")


def verify_s2_hold_to_arm_with_usb_dongle(robot: SerialCli, mock: SerialCli) -> None:
    mock.command("SET LX=127 LY=127 RX=127 RY=127 L2=0 R2=0 HAT=C BTN=", seconds=0.3)
    assert_status_field(
        robot,
        "S2 ESC hold-arm waiting low pulse",
        lambda s: s.s2_arm in {"waiting", "holding"} and s.s2_pulse_us == 125,
        timeout=3.0,
    )
    mock.command("SET BTN=B", seconds=0.2)
    assert_status_field(
        robot,
        "S2 ESC hold-arm source held",
        lambda s: (s.buttons & 0x02) != 0 and s.s2_arm in {"holding", "low1", "high", "low2", "armed"},
        timeout=2.0,
    )
    assert_status_field(
        robot,
        "S2 ESC arming sequence high pulse",
        lambda s: s.s2_arm == "high" and s.s2_pulse_us == 250,
        timeout=3.0,
    )
    assert_status_field(
        robot,
        "S2 ESC arming sequence completes",
        lambda s: s.s2_arm == "armed",
        timeout=4.0,
    )
    mock.command("SET BTN=B R2=128", seconds=0.3)
    assert_status_field(
        robot,
        "S2 ESC throttle accepted after arming",
        lambda s: s.s2_arm == "armed" and s.rt == 512 and s.s2_pulse_us > 125,
        timeout=3.0,
    )
    mock.command("SET LX=127 LY=127 RX=127 RY=127 L2=0 R2=0 HAT=C BTN=", seconds=0.3)
    print("PASS S2 ESC hold-to-arm sequence via USB dongle")


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




def configure_drive(api: RobotApi, drive: dict) -> None:
    resp = api.post_json("/api/config", {"drive": drive})
    if resp.get("ok") is not True:
        raise BenchError(f"API drive patch failed: {resp}")
    echoed = api.get("/api/config").get("drive", {})
    for key, value in drive.items():
        if echoed.get(key) != value:
            raise BenchError(f"API drive echo mismatch for {key}: expected {value!r}, got {echoed.get(key)!r}; drive={echoed}")


def restore_default_drive(api: RobotApi) -> None:
    configure_drive(api, {
        "layout": "differential",
        "method": "tank",
        "left_axis": "LY",
        "right_axis": "RY",
        "throttle_axis": "LY",
        "steering_axis": "LX",
        "drive_motor_output": "M1",
        "steering_output": "S1",
        "precision_source": "NONE",
        "precision_scale_pct": 50,
        "brake_source": "NONE",
        "invert_steering_source": "NONE",
    })



def configure_manual_m1(api: RobotApi, *, mode: str, primary: str = "A", duty: int = 100, freq: int = 20000) -> None:
    # Avoid transient validation failures when switching between analog-capable
    # proportional mode and digital-only momentary/latching modes. The firmware
    # validates after each parsed key, so move through a safe disabled/NONE state.
    safe = api.post_json("/api/config", {"M1": {"motor_mode": "disabled", "primary": "NONE"}})
    if safe.get("ok") is not True:
        raise BenchError(f"API configure manual M1 safe transition failed: {safe}")
    resp = api.post_json("/api/config", {
        "M1": {
            "display_name": "Motor 1",
            "direction": "normal",
            "servo_mode": "bi",
            "deadzone": 10,
            "motor_mode": mode,
            "primary": primary,
            "secondary": "NONE",
            "purpose": "drive",
            "protocol": "none",
            "semantics": "none",
            "pwm_frequency_hz": freq,
            "pwm_duty_pct": duty,
            "power_good": "default",
            "power_warn": "default",
            "power_low": "default",
        }
    })
    if resp.get("ok") is not True:
        raise BenchError(f"API configure manual M1 failed: {resp}")


def verify_manual_motor_outputs(api: RobotApi, robot: SerialCli) -> None:
    # Out-of-range motor PWM frequency should be rejected at the API/config layer.
    try:
        api.post_json("/api/config", {"M1": {"motor_mode": "momentary", "primary": "LY"}})
        raise BenchError("manual M1 momentary analog stick source unexpectedly succeeded")
    except BenchError as exc:
        if "HTTP Error 400" not in str(exc) and "invalid patch" not in str(exc):
            raise
    try:
        api.post_json("/api/config", {"M1": {"motor_mode": "latching", "primary": "RT"}})
        raise BenchError("manual M1 latching analog trigger source unexpectedly succeeded")
    except BenchError as exc:
        if "HTTP Error 400" not in str(exc) and "invalid patch" not in str(exc):
            raise
    print("PASS manual M1 momentary/latching reject analog stick/trigger sources")

    try:
        api.post_json("/api/config", {"M1": {"pwm_frequency_hz": 999}})
        raise BenchError("M1 PWM frequency below lower bound unexpectedly succeeded")
    except BenchError as exc:
        if "HTTP Error 400" not in str(exc) and "invalid patch" not in str(exc):
            raise
    try:
        api.post_json("/api/config", {"M1": {"pwm_frequency_hz": 40001}})
        raise BenchError("M1 PWM frequency above upper bound unexpectedly succeeded")
    except BenchError as exc:
        if "HTTP Error 400" not in str(exc) and "invalid patch" not in str(exc):
            raise
    print("PASS M1 PWM frequency bounds reject out-of-range values")

    resp = api.post_json("/api/config", {"M1": {"pwm_frequency_hz": 30000}})
    if resp.get("ok") is not True:
        raise BenchError(f"API M1 valid PWM frequency failed: {resp}")
    if api.get("/api/config").get("outputs", {}).get("M1", {}).get("pwm", {}).get("frequency_hz") != 30000:
        raise BenchError("API M1 PWM frequency echo mismatch after valid patch")
    print("PASS M1 PWM frequency accepts valid in-range value")

    configure_drive(api, {
        "layout": "differential",
        "method": "none",
        "left_axis": "LY",
        "right_axis": "RY",
        "throttle_axis": "LY",
        "steering_axis": "LX",
        "drive_motor_output": "M1",
        "steering_output": "S1",
        "precision_source": "NONE",
        "precision_scale_pct": 50,
        "brake_source": "NONE",
        "invert_steering_source": "NONE",
    })
    configure_manual_m1(api, mode="momentary", primary="A", duty=100, freq=20000)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex()})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench neutral before manual M1 failed: {resp}")
    assert_status_field(robot, "manual M1 momentary released -> stop", lambda s: s.drive_method == "none" and s.drive_left == 0 and s.drive_right == 0)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(b0=0x01)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench A for manual M1 failed: {resp}")
    assert_status_field(robot, "manual M1 momentary A -> M1 only", lambda s: s.buttons == 1 and s.drive_method == "none" and s.drive_left > 450 and s.drive_right == 0)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex()})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench release for manual M1 failed: {resp}")
    assert_status_field(robot, "manual M1 momentary release -> stop", lambda s: s.buttons == 0 and s.drive_left == 0 and s.drive_right == 0)

    configure_manual_m1(api, mode="latching", primary="A", duty=100, freq=20000)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(b0=0x01)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench A latch-on failed: {resp}")
    assert_status_field(robot, "manual M1 latch A toggles on", lambda s: s.buttons == 1 and s.drive_left > 450 and s.drive_right == 0)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex()})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench release after latch-on failed: {resp}")
    assert_status_field(robot, "manual M1 latch stays on after release", lambda s: s.buttons == 0 and s.drive_left > 450 and s.drive_right == 0)
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(b0=0x01)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench A latch-off failed: {resp}")
    assert_status_field(robot, "manual M1 latch A toggles off", lambda s: s.buttons == 1 and s.drive_left == 0 and s.drive_right == 0)

    restore_default_drive(api)
    configure_manual_m1(api, mode="proportional", primary="LY", duty=100, freq=20000)
    print("PASS manual M1 momentary/latching Drive Method None coverage")

def verify_composable_drive_setup(api: RobotApi, robot: SerialCli) -> None:
    configure_drive(api, {
        "layout": "differential",
        "method": "arcade",
        "throttle_axis": "RT_MINUS_LT",
        "steering_axis": "LX",
        "precision_source": "NONE",
        "precision_scale_pct": 50,
        "brake_source": "NONE",
        "invert_steering_source": "NONE",
    })
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=128, l2=0, lx=127)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench drive trigger throttle failed: {resp}")
    base = assert_status_field(
        robot,
        "drive RT/LT trigger throttle -> forward arcade",
        lambda s: s.rt == 512 and s.lt == 0 and s.drive_throttle > 200 and abs(s.drive_steering) <= 4 and s.drive_left > 200 and s.drive_right > 200 and s.m1_speed > 0 and s.m2_speed > 0 and s.m1_fwd_duty != s.m1_rev_duty and s.m2_fwd_duty != s.m2_rev_duty,
    )

    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=128, l2=0, lx=0)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench drive trigger + steering failed: {resp}")
    assert_status_field(
        robot,
        "drive left stick steering mixes M1/M2",
        lambda s: s.drive_throttle > 200 and s.drive_steering < -450 and s.drive_left < s.drive_right,
    )

    configure_drive(api, {
        "layout": "differential",
        "method": "arcade",
        "throttle_axis": "RT_MINUS_LT",
        "steering_axis": "LX",
        "precision_source": "L1",
        "precision_scale_pct": 50,
        "brake_source": "NONE",
        "invert_steering_source": "NONE",
    })
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=128, lx=127, b0=0x40)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench precision modifier failed: {resp}")
    assert_status_field(
        robot,
        "drive precision modifier scales throttle",
        lambda s, base_throttle=base.drive_throttle: 90 <= s.drive_throttle <= max(110, base_throttle - 80) and s.drive_throttle < base_throttle,
    )

    configure_drive(api, {
        "layout": "differential",
        "method": "arcade",
        "throttle_axis": "RT_MINUS_LT",
        "steering_axis": "LX",
        "precision_source": "NONE",
        "precision_scale_pct": 50,
        "brake_source": "B",
        "invert_steering_source": "NONE",
    })
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=128, lx=0, b0=0x02)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench brake modifier failed: {resp}")
    assert_status_field(
        robot,
        "drive brake modifier zeroes throttle and steering",
        lambda s: s.buttons & 0x02 and s.drive_throttle == 0 and s.drive_steering == 0 and s.drive_left == 0 and s.drive_right == 0,
    )

    configure_drive(api, {
        "layout": "differential",
        "method": "arcade",
        "throttle_axis": "DPAD_Y",
        "steering_axis": "DPAD_X",
        "precision_source": "NONE",
        "precision_scale_pct": 50,
        "brake_source": "NONE",
        "invert_steering_source": "NONE",
    })
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(hat=0)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench dpad drive failed: {resp}")
    assert_status_field(
        robot,
        "drive DPAD_Y throttle",
        lambda s: s.dpad == 1 and s.drive_throttle > 450 and s.drive_left > 450 and s.drive_right > 450,
    )

    restore_s1_servo(api)
    configure_drive(api, {
        "layout": "servo_steering",
        "method": "servo_steering",
        "drive_motor_output": "M1",
        "steering_output": "S1",
        "throttle_axis": "RT_MINUS_LT",
        "steering_axis": "LX",
        "precision_source": "NONE",
        "precision_scale_pct": 50,
        "brake_source": "NONE",
        "invert_steering_source": "NONE",
    })
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=128, lx=0)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench servo steering failed: {resp}")
    assert_status_field(
        robot,
        "servo steering layout maps LX to S1 pulse and RT to M1",
        lambda s: s.drive_throttle > 200 and s.drive_left > 200 and s.drive_right == 0 and s.drive_steering < -450 and 990 <= s.s1_pulse_us <= 1020,
    )
    restore_default_drive(api)
    restore_s1_servo(api)
    print("PASS composable drive setup trigger/dpad/modifier/servo-steering coverage")


def verify_s1_servo_pulse_range(api: RobotApi, robot: SerialCli) -> None:
    resp = api.post_json("/api/config", {
        "S1": {
            "display_name": "S1 Range",
            "direction": "normal",
            "servo_mode": "bi",
            "deadzone": 0,
            "primary": "LX",
            "secondary": "NONE",
            "purpose": "servo",
            "protocol": "rc_servo_pwm",
            "semantics": "position_servo",
            "weapon_safety": False,
            "failsafe": "safe_state",
            "min_pulse_us": 1000,
            "center_pulse_us": 1500,
            "max_pulse_us": 2000,
            "frame_hz": 50,
            "power_good": "default",
            "power_warn": "default",
            "power_low": "default",
        }
    })
    if resp.get("ok") is not True:
        raise BenchError(f"API config S1 servo pulse range failed: {resp}")
    for label, lx, predicate in [
        ("S1 servo LX min -> min pulse", 0, lambda s: 990 <= s.s1_pulse_us <= 1020),
        ("S1 servo LX center -> center pulse", 127, lambda s: 1480 <= s.s1_pulse_us <= 1520),
        ("S1 servo LX max -> max pulse", 255, lambda s: 1980 <= s.s1_pulse_us <= 2010),
    ]:
        resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(lx=lx)})
        if resp.get("ok") is not True:
            raise BenchError(f"API bench {label} failed: {resp}")
        assert_status_field(robot, label, predicate)
    restore_s1_servo(api)
    print("PASS S1 servo pulse min/center/max coverage")


def verify_power_behavior_runtime(api: RobotApi, robot: SerialCli) -> None:
    try:
        clear_bench_battery(api)
    except BenchError:
        pass
    configure_drive(api, {
        "layout": "differential",
        "method": "arcade",
        "throttle_axis": "RT_MINUS_LT",
        "steering_axis": "LX",
        "precision_source": "NONE",
        "precision_scale_pct": 50,
        "brake_source": "NONE",
        "invert_steering_source": "NONE",
    })
    patch_output_power(api, "M1", warn="reduce", low="disable")
    patch_output_power(api, "M2", warn="reduce", low="disable")
    try:
        set_bench_battery(api, "good")
        resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=192, lx=127)})
        if resp.get("ok") is not True:
            raise BenchError(f"API bench power GOOD drive failed: {resp}")
        good = assert_status_field(
            robot,
            "power GOOD allows full drive",
            lambda s: s.drive_left > 300 and s.drive_right > 300 and s.m1_speed > 150 and s.m2_speed > 150,
        )

        set_bench_battery(api, "warn")
        resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=192, lx=127)})
        if resp.get("ok") is not True:
            raise BenchError(f"API bench power WARN drive failed: {resp}")
        assert_status_field(
            robot,
            "power WARN reduces drive to about half",
            lambda s, baseline=good.drive_left: 120 <= s.drive_left < baseline and 120 <= s.drive_right < baseline and s.m1_speed < good.m1_speed and s.m2_speed < good.m2_speed,
        )

        set_bench_battery(api, "low")
        resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=192, lx=127)})
        if resp.get("ok") is not True:
            raise BenchError(f"API bench power LOW drive failed: {resp}")
        assert_status_field(
            robot,
            "power LOW disables drive",
            lambda s: s.drive_left == 0 and s.drive_right == 0 and s.m1_speed == 0 and s.m2_speed == 0 and s.m1_dir == "stop" and s.m2_dir == "stop",
        )
    finally:
        patch_output_power(api, "M1")
        patch_output_power(api, "M2")
        clear_bench_battery(api)
        restore_default_drive(api)
    print("PASS power behavior WARN reduce / LOW disable runtime coverage")


def verify_disconnect_failsafe(api: RobotApi, robot: SerialCli) -> None:
    configure_drive(api, {
        "layout": "differential",
        "method": "arcade",
        "throttle_axis": "RT_MINUS_LT",
        "steering_axis": "LX",
        "precision_source": "NONE",
        "precision_scale_pct": 50,
        "brake_source": "NONE",
        "invert_steering_source": "NONE",
    })
    resp = api.post("/api/bench/hid", {"hex": pack_8bitdo_hex(r2=192, lx=127)})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench before disconnect failsafe failed: {resp}")
    assert_status_field(robot, "failsafe precondition drive moving", lambda s: s.m1_speed > 0 and s.m2_speed > 0)
    robot.command("disconnect", seconds=0.8)
    assert_status_field(
        robot,
        "disconnect failsafe stops drive motors",
        lambda s: s.drive_left == 0 and s.drive_right == 0 and s.m1_speed == 0 and s.m2_speed == 0,
        timeout=4.0,
    )
    print("PASS disconnect failsafe stops drive motors")


def collect_drive_sim_samples(api: RobotApi, robot: SerialCli, *, hid_hex: str, duration_s: float, start_t_s: float) -> list[TimedStatus]:
    resp = api.post("/api/bench/hid", {"hex": hid_hex})
    if resp.get("ok") is not True:
        raise BenchError(f"API bench hid for drive-sim failed: {resp}")
    samples: list[TimedStatus] = []
    end = time.monotonic() + duration_s
    while time.monotonic() < end or not samples:
        now = time.monotonic()
        try:
            samples.append(TimedStatus(now - start_t_s, robot_status(robot, seconds=0.15)))
        except BenchError:
            if not samples:
                raise
        time.sleep(0.05)
    return samples


def run_drive_sim_scenario(
    api: RobotApi,
    robot: SerialCli,
    *,
    board,
    name: str,
    kind: Any,
    active_hid: str,
    active_duration_s: float,
    assertions,
    description: str,
):
    start = time.monotonic()
    samples = collect_drive_sim_samples(api, robot, hid_hex=active_hid, duration_s=active_duration_s, start_t_s=start)
    samples.extend(collect_drive_sim_samples(api, robot, hid_hex=pack_8bitdo_hex(), duration_s=0.25, start_t_s=start))
    result = simulate_status_samples(
        name=name,
        kind=kind,
        samples=samples,
        assertions=assertions,
        board=board,
        description=description,
    )
    if not result.passed:
        details = "; ".join(f"{r.name}={r.passed} ({r.detail})" for r in result.assertion_results)
        raise BenchError(f"drive-sim scenario {name} failed: {details}")
    print(f"PASS drive-sim {name}: {result.trajectory.metrics()}")
    return result


def run_drive_sim_tests(api: RobotApi, robot: SerialCli, *, board_rev: int, out_path: str) -> None:
    board = load_board_data(board_rev)
    print(f"INFO drive-sim board: {board.summary}")
    status = api.get("/api/bench/hid/status")
    if status.get("runtime_enabled") is not True:
        enabled = api.post("/api/bench/hid/enable")
        if enabled.get("ok") is not True:
            raise BenchError(f"API bench enable failed for drive-sim: {enabled}")

    results = []
    try:
        configure_drive(api, {
            "layout": "differential",
            "method": "arcade",
            "throttle_axis": "RT_MINUS_LT",
            "steering_axis": "LX",
            "precision_source": "NONE",
            "precision_scale_pct": 50,
            "brake_source": "NONE",
            "invert_steering_source": "NONE",
        })
        diff_kind = "four_wheel_skid" if board.num_drive_motors >= 4 else "differential"
        results.append(run_drive_sim_scenario(
            api, robot, board=board,
            name=f"board{board.rev}_firmware_arcade_forward",
            kind=diff_kind,
            active_hid=pack_8bitdo_hex(r2=192, lx=127),
            active_duration_s=0.8,
            assertions=[MovesForward(), EndsStopped()],
            description=f"{board.summary}: live firmware arcade RT throttle should simulate forward motion.",
        ))
        results.append(run_drive_sim_scenario(
            api, robot, board=board,
            name=f"board{board.rev}_firmware_arcade_left_arc",
            kind=diff_kind,
            active_hid=pack_8bitdo_hex(r2=128, lx=80),
            active_duration_s=0.55,
            assertions=[ArcsLeft(min_distance_m=0.03), EndsStopped()],
            description=f"{board.summary}: live firmware arcade steering-left should simulate a left arc.",
        ))
        results.append(run_drive_sim_scenario(
            api, robot, board=board,
            name=f"board{board.rev}_firmware_arcade_right_arc",
            kind=diff_kind,
            active_hid=pack_8bitdo_hex(r2=128, lx=174),
            active_duration_s=0.55,
            assertions=[ArcsRight(min_distance_m=0.03), EndsStopped()],
            description=f"{board.summary}: live firmware arcade steering-right should simulate a right arc.",
        ))

        restore_s1_servo(api)
        configure_drive(api, {
            "layout": "servo_steering",
            "method": "servo_steering",
            "drive_motor_output": "M1",
            "steering_output": "S1",
            "throttle_axis": "RT_MINUS_LT",
            "steering_axis": "LX",
            "precision_source": "NONE",
            "precision_scale_pct": 50,
            "brake_source": "NONE",
            "invert_steering_source": "NONE",
        })
        results.append(run_drive_sim_scenario(
            api, robot, board=board,
            name=f"board{board.rev}_firmware_servo_steer_left_arc",
            kind="servo_steer",
            active_hid=pack_8bitdo_hex(r2=128, lx=0),
            active_duration_s=0.55,
            assertions=[ArcsLeft(), EndsStopped()],
            description=f"{board.summary}: live firmware servo-steering low S1 pulse should simulate a left arc.",
        ))
        results.append(run_drive_sim_scenario(
            api, robot, board=board,
            name=f"board{board.rev}_firmware_servo_steer_right_arc",
            kind="servo_steer",
            active_hid=pack_8bitdo_hex(r2=128, lx=255),
            active_duration_s=0.55,
            assertions=[ArcsRight(), EndsStopped()],
            description=f"{board.summary}: live firmware servo-steering high S1 pulse should simulate a right arc.",
        ))
    finally:
        api.post("/api/bench/hid", {"hex": pack_8bitdo_hex()})
        restore_default_drive(api)
        restore_s1_servo(api)

    report = render_report(results, out_path)
    print(f"PASS drive-sim report: {report}")


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

    restore_s2_servo(api)
    assert_status_field(robot, "S2 restored before ESC arming test", lambda s: s.s2_arm == "inactive", timeout=3.0)
    verify_s2_esc_protocol_presets(api, robot)
    restore_s2_servo(api)
    assert_status_field(robot, "S2 restored before ESC arming test", lambda s: s.s2_arm == "inactive", timeout=3.0)
    configure_s2_esc_arming(api)
    verify_s2_hold_to_arm_with_usb_dongle(robot, mock)

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

    verify_composable_drive_setup(api, robot)
    verify_manual_motor_outputs(api, robot)
    verify_s1_servo_pulse_range(api, robot)
    verify_power_behavior_runtime(api, robot)
    verify_disconnect_failsafe(api, robot)

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


def verify_ota_update(api_base: str, firmware: Path, timeout: float) -> None:
    """Upload a built binary through the public OTA endpoint and verify reboot."""
    if not firmware.is_file() or firmware.stat().st_size == 0:
        raise BenchError(f"OTA firmware missing or empty: {firmware}")
    boundary = "----combatRobotBenchOTA"
    payload = firmware.read_bytes()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"update\"; filename=\"{firmware.name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(api_base + "/api/ota", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))})
    try:
        with urllib.request.urlopen(req, timeout=timeout + 30) as response:
            result = json.loads(response.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
        raise BenchError(f"OTA upload request failed: {exc}") from exc
    if result.get("ok") is not True:
        raise BenchError(f"OTA endpoint rejected firmware: {result}")
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(api_base + "/api/status", timeout=timeout) as response:
                json.loads(response.read().decode())
                print("PASS OTA upload and post-reboot API liveness")
                return
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
            time.sleep(1)
    raise BenchError("OTA accepted firmware but board did not return through /api/status")


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

        if args.drive_sim_only:
            if args.skip_api:
                raise BenchError("--drive-sim-only requires WiFi/API access; remove --skip-api")
            run_drive_sim_tests(RobotApi(args.api_base, timeout=args.api_timeout), robot, board_rev=args.board_rev, out_path=args.drive_sim_out)
        elif args.skip_api:
            print("SKIP WiFi API tests (--skip-api)")
        else:
            run_api_tests(RobotApi(args.api_base, timeout=args.api_timeout), robot, mock)
            if args.ota_bin:
                verify_ota_update(args.api_base, Path(args.ota_bin), args.api_timeout)
            if args.drive_sim:
                run_drive_sim_tests(RobotApi(args.api_base, timeout=args.api_timeout), robot, board_rev=args.board_rev, out_path=args.drive_sim_out)

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
    p.add_argument("--ota-bin", help="Built firmware.bin to upload via /api/ota after normal API checks")
    p.add_argument("--drive-sim", action="store_true", help="After normal API bench tests, run virtual drive-sim scenarios from live firmware telemetry")
    p.add_argument("--drive-sim-only", action="store_true", help="Run only liveness/link setup plus live-telemetry virtual drive-sim scenarios")
    p.add_argument("--drive-sim-out", default="artifacts/drive-sim/bench-live.html", help="HTML output path for --drive-sim report")
    p.add_argument("--board-rev", type=int, default=2, choices=[2, 3], help="BOARD_REV metadata to use for drive simulation")
    args = p.parse_args(list(argv) if argv is not None else None)
    try:
        run(args)
        return 0
    except BenchError as exc:
        print(f"BENCH_E2E FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
