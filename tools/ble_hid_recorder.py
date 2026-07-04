#!/usr/bin/env python3
"""
ble_hid_recorder.py - walk-the-user-through 8BitDo HID report recorder.

Walks you through a sequence of phases. In each phase, you perform the action
the script prompts for (move sticks, press buttons, etc.). The script records
every HID notification the 8BitDo sends over BLE.

Phase advance is *always* manual: type Enter to confirm you've finished the
current phase. The only time-bounded phase is IDLE, which is a fixed 5-second
window for a clean baseline. Even there, you confirm the next phase.

The result is a complete log of raw HID bytes plus a structured parse for
each phase, written to a JSONL file plus a final summary JSON. That gives us
ground truth for the byte layout of the actual 8BitDo Ultimate 2 reports we
pair to in combat-robot-v2.

Phases (type Enter at each prompt to advance):
  1. PAIR         - put 8BitDo in pairing mode, scan, connect
  2. APPROVE      - approve the Windows Bluetooth prompt, then press Enter
  3. SUBSCRIBE    - subscribe to notifiable HID/report characteristics
  4. IDLE         - 5 s window, do not touch the controller
  4. STICKS_CENTER / LEFT / RIGHT / DIAG / BOTTOM - five sub-phases
  5. DPAD         - press each direction
  6. FACE         - press A, B, X, Y
  7. BUMPERS      - press L1, R1, L2, R2
  8. STICK_CLICKS - press L3, R3
  9. MENU         - press SELECT, START, HOME
 10. DONE         - print summary, exit

Output (per run):
  tools/ble_recordings/hid-YYYYMMDD-HHMMSS.jsonl    one line per HID report
  tools/ble_recordings/hid-YYYYMMDD-HHMMSS.summary.json  per-phase stats

Run:
  /c/Users/kbrow/.platformio/penv/Scripts/python.exe tools/ble_hid_recorder.py
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
import time
from collections import Counter
from pathlib import Path

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

# ---- Output paths ----------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = SCRIPT_DIR.parent / "tools" / "ble_recordings"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def make_log_paths() -> tuple[Path, Path]:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    jsonl = LOG_DIR / f"hid-{stamp}.jsonl"
    summary = LOG_DIR / f"hid-{stamp}.summary.json"
    return jsonl, summary


# ---- HID Report parsing -----------------------------------------------------
#
# We don't yet know the exact byte layout this 8BitDo uses in BLE mode.
# The script records RAW BYTES, then the summary printout shows the parsed
# fields under a "candidate layout" that matches the firmware's current
# assumption in components/ble_gamepad/src/ble_gamepad.cpp. If the real
# hardware disagrees, the recorded bytes let us see by exactly how much.

HID_SERVICE_UUID = "00001812-0000-1000-8000-00805f9b34fb"
HID_REPORT_CHAR_UUID = "00002a4d-0000-1000-8000-00805f9b34fb"


def decode_report(data: bytes) -> dict | None:
    """Best-effort decode of a 9-byte HID report under the layout the firmware uses."""
    if len(data) < 9:
        return None
    return {
        "lx": data[0],
        "ly": data[1],
        "rx": data[2],
        "ry": data[3],
        "buttons_low": data[4],
        "buttons_high": data[5],
        "lt": data[6],
        "rt": data[7],
        "dpad": data[8],
        "buttons_decoded": {
            "A": bool(data[4] & 0x01),
            "B": bool(data[4] & 0x02),
            "X": bool(data[4] & 0x04),
            "Y": bool(data[4] & 0x08),
            "L1": bool(data[4] & 0x10),
            "R1": bool(data[4] & 0x20),
            "L2": bool(data[4] & 0x40),
            "R2": bool(data[4] & 0x80),
            "SELECT": bool(data[5] & 0x01),
            "START":  bool(data[5] & 0x02),
            "L3": bool(data[5] & 0x04),
            "R3": bool(data[5] & 0x08),
            "HOME": bool(data[5] & 0x10),
        },
        "dpad_decoded": {
            0: "N", 1: "NE", 2: "E", 3: "SE", 4: "S",
            5: "SW", 6: "W", 7: "NW", 8: "center",
        }.get(data[8], f"0x{data[8]:02x}"),
    }


# ---- I/O helpers ------------------------------------------------------------


def confirm(prompt: str) -> bool:
    """Prompt the user; treat any input as confirmation (empty, 'y', 'next', etc.)."""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line = sys.stdin.readline()
    s = line.strip().lower()
    if s in ("q", "quit", "exit", "x"):
        print("  abort requested.")
        raise SystemExit(2)
    return True  # Enter (or any non-quit input) advances


# ---- Scan + connect --------------------------------------------------------


async def scan_for_8bitdo(timeout: float = 8.0):
    """Return the BLEDevice for the first 8BitDo we see, or None."""
    from bleak import BleakScanner

    print(f"  scanning for 8BitDo... ({timeout:.0f}s window)")
    sys.stdout.flush()

    def match_8bitdo(device: BLEDevice, adv: AdvertisementData):
        n = (device.name or adv.local_name or "")
        return ("8BitDo" in n) or ("Ultimate" in n)

    try:
        device = await BleakScanner.find_device_by_filter(
            match_8bitdo, timeout=timeout,
        )
    except Exception as e:
        print(f"  scan failed: {e!r}")
        return None

    if device is None:
        print("  no 8BitDo found in this scan window.")
        return None

    rssi = ""
    print(f"  found: {device.address}  name={device.name!r}")
    return device


async def connect_with_retry(addr: str):
    """Connect to addr, retrying on TimeoutError. Returns the BleakClient."""
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            print(f"  connecting to {addr} (attempt {attempt}/3)...")
            sys.stdout.flush()
            client = BleakClient(addr, timeout=30.0)
            await client.connect()
            if client.is_connected:
                print(f"  connected.")
                return client
            print("  connect() returned but client is not connected.")
            await client.disconnect()
        except (asyncio.TimeoutError, TimeoutError) as e:
            last_err = e
            print(f"  attempt {attempt} timed out: {e!r}")
            print("    (Windows BLE GATT enumeration can stall on subsequent")
            print("     connects; usually retrying, or unpairing from Settings")
            print("     -> Bluetooth & devices, then trying again, works.)")
        except Exception as e:
            last_err = e
            print(f"  attempt {attempt} failed: {e!r}")
        await asyncio.sleep(2.0)

    print(f"  giving up after 3 attempts. last error: {last_err!r}")
    return None


def _props(ch) -> set[str]:
    """Bleak exposes characteristic properties as a list-like object."""
    return set(ch.properties or [])


def _is_notify_char(ch) -> bool:
    props = _props(ch)
    return "notify" in props or "indicate" in props


STANDARD_NOTIFY_SERVICES = {
    "00001800-0000-1000-8000-00805f9b34fb",  # GAP (Device Name, Appearance)
    "00001801-0000-1000-8000-00805f9b34fb",  # GATT (Service Changed)
    "0000180f-0000-1000-8000-00805f9b34fb",  # Battery
}


async def find_hid_input_chars(client: BleakClient, *, notify_handle: int | None = None,
                               include_standard_notify: bool = False):
    """Return notifiable input-report candidates.

    Prefer, in order:
      1. Explicit --notify-handle.
      2. HID Report (0x2A4D) characteristics under HID service (0x1812).
      3. Vendor/custom notifiable characteristics, e.g. 8BitDo's
         00010203-0405-0607-0809-0a0b0c0d2b12 under ...1912.
      4. Any notifiable HID-service char.
      5. Any notifiable char only if --include-standard-notify is set.

    We intentionally skip GAP/GATT/Battery notify chars by default because
    subscribing to them can hang or produce irrelevant events on Windows.
    """
    try:
        services = client.services
    except Exception as e:
        print(f"  could not read GATT services from client.services: {e!r}")
        return []
    if services is None:
        print("  no GATT services are available yet; approve Windows pairing and rerun.")
        return []

    handle_match = []
    report_notify = []
    hid_notify = []
    vendor_notify = []
    all_notify = []
    print("  GATT inventory:")
    for svc in services:
        svc_uuid = str(svc.uuid).lower()
        svc_is_hid = svc_uuid.startswith("00001812")
        svc_is_standard_notify = svc_uuid in STANDARD_NOTIFY_SERVICES
        print(f"    service {svc.uuid}")
        for ch in svc.characteristics:
            ch_uuid = str(ch.uuid).lower()
            props = sorted(_props(ch))
            is_notify = _is_notify_char(ch)
            print(f"      char handle={ch.handle:<4} uuid={ch.uuid} props={','.join(props) or '-'}")
            if notify_handle is not None and ch.handle == notify_handle:
                if is_notify:
                    handle_match.append(ch)
                else:
                    print(f"  requested handle {notify_handle} is not notifiable; props={props}")
            if not is_notify:
                continue
            all_notify.append(ch)
            if svc_is_hid:
                hid_notify.append(ch)
            if svc_is_hid and ch_uuid.startswith("00002a4d"):
                report_notify.append(ch)
            if not svc_is_hid and not svc_is_standard_notify:
                vendor_notify.append(ch)

    if handle_match:
        print(f"  using explicit --notify-handle {notify_handle}.")
        return handle_match
    if notify_handle is not None:
        print(f"  explicit --notify-handle {notify_handle} was not found/usable.")
        return []
    if report_notify:
        print(f"  using {len(report_notify)} HID Report notify char(s).")
        return report_notify
    if vendor_notify:
        print(f"  no HID Report notify char; using {len(vendor_notify)} vendor/custom notify char(s).")
        return vendor_notify
    if hid_notify:
        print(f"  no notifiable 0x2A4D Report char; using {len(hid_notify)} notifiable HID-service char(s).")
        return hid_notify
    if include_standard_notify and all_notify:
        print(f"  using {len(all_notify)} notifiable char(s) from all services because --include-standard-notify was set.")
        return all_notify
    if all_notify:
        print("  only standard GAP/GATT/Battery notify chars were found; skipping them by default.")
        print("  Re-run with --include-standard-notify if you explicitly want to subscribe to them.")
    return []


# ---- Phases ----------------------------------------------------------------


PHASE_DEFS = [
    ("PAIR", "Put the 8BitDo in BLE pairing mode (Start+Pair, solid blue LED)."),
    ("SUBSCRIBE", "Subscribe to the HID input-report characteristic."),
    ("IDLE", "Don't touch the controller. 5-second baseline."),
    ("STICKS_CENTER", "Rest both sticks at center, then release."),
    ("STICKS_LEFT_UP", "Push the LEFT stick fully UP. Hold 1s. Release."),
    ("STICKS_RIGHT_RIGHT", "Push the RIGHT stick fully RIGHT. Hold 1s. Release."),
    ("STICKS_LEFT_DIAG", "Push the LEFT stick to UPPER-LEFT corner. Hold."),
    ("STICKS_LEFT_DOWN", "Push the LEFT stick fully DOWN. Hold 1s. Release."),
    ("DPAD", "Press UP, then DOWN, then LEFT, then RIGHT."),
    ("FACE", "Press A. Release. Press B. Release. Press X. Release. Press Y. Release."),
    ("BUMPERS", "Press L1. Release. Press R1. Release. Hold L2 down 1s. Release. Hold R2 down 1s. Release."),
    ("STICK_CLICKS", "Press L3 (left stick click). Release. Press R3 (right stick click). Release."),
    ("MENU", "Press SELECT/SHARE. Release. Press START/OPTIONS. Release. Press HOME/PS. Release."),
    ("DONE", "All phases recorded. Writing summary."),
]


# ---- Main loop -------------------------------------------------------------


async def run() -> int:
    parser = argparse.ArgumentParser(description="Walk-the-user HID recorder")
    parser.add_argument("--scan-timeout", type=float, default=8.0,
                        help="seconds per BLE scan attempt")
    parser.add_argument("--idle-seconds", type=float, default=5.0,
                        help="length of the IDLE baseline phase")
    parser.add_argument("--notify-handle", type=int, default=None,
                        help="force a specific GATT characteristic handle to subscribe to")
    parser.add_argument("--include-standard-notify", action="store_true",
                        help="also consider GAP/GATT/Battery notify characteristics")
    args = parser.parse_args()

    jsonl_path, summary_path = make_log_paths()
    print(f"Logging to:  {jsonl_path}")
    print(f"Summary to:  {summary_path}")
    print(f"Tail in another shell:  tail -f {jsonl_path}")
    print()

    log_fh = jsonl_path.open("w", encoding="utf-8")

    state = {
        "report_seq": 0,
        "report_count": 0,
        "all_reports": [],
        "connected_address": None,
    }
    current_phase = ["PAIR"]

    def record(data: bytes, sender=None) -> None:
        state["report_seq"] += 1
        entry = {
            "ts": time.time(),
            "iso": dt.datetime.now().isoformat(timespec="milliseconds"),
            "phase": current_phase[0],
            "seq": state["report_seq"],
            "sender": str(sender) if sender is not None else None,
            "raw_hex": data.hex(),
            "len": len(data),
            "decoded": decode_report(data),
        }
        log_fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
        log_fh.flush()
        state["report_count"] += 1
        state["all_reports"].append(entry)
        # Compact print so you can watch the bytes stream by.
        d = entry["decoded"]
        dpad = d["dpad_decoded"] if d else "?"
        bts = ",".join(k for k, v in (d["buttons_decoded"].items() if d else []) if v) or "-"
        print(f"    [{entry['phase']:>20}] seq={entry['seq']:>5}  "
              f"len={entry['len']:>2}  "
              f"LX={d['lx'] if d else '?'} LY={d['ly'] if d else '?'} "
              f"RX={d['rx'] if d else '?'} RY={d['ry'] if d else '?'} "
              f"LT={d['lt'] if d else '?'} RT={d['rt'] if d else '?'} "
              f"dpad={dpad:>5} btns={bts}")

    # ---- PHASE 1: PAIR ------------------------------------------------
    print(f"[{PHASE_DEFS[0][0]}] {PHASE_DEFS[0][1]}")
    device = None
    while device is None:
        device = await scan_for_8bitdo(timeout=args.scan_timeout)
        if device is None:
            confirm("  Press Enter to scan again, or 'q' + Enter to quit.\n> ")
    state["connected_address"] = device.address

    # ---- Connect (with retry) -----------------------------------------
    client = await connect_with_retry(device.address)
    if client is None:
        log_fh.close()
        return 2

    chars = []
    try:
        print()
        print("  If Windows shows a Bluetooth pairing/approval prompt, approve it now.")
        print("  Wait until Windows says the controller is connected/ready, then press Enter.")
        confirm("> ")
        await asyncio.sleep(0.5)

        # ---- PHASE 2: SUBSCRIBE ---------------------------------------
        current_phase[0] = PHASE_DEFS[1][0]
        print(f"\n[{current_phase[0]}] {PHASE_DEFS[1][1]}")
        chars = await find_hid_input_chars(
            client,
            notify_handle=args.notify_handle,
            include_standard_notify=args.include_standard_notify,
        )
        if not chars:
            print("  FATAL: no notifiable GATT characteristics found.")
            print("  If Windows just paired this controller, run the script again once")
            print("  Bluetooth Settings shows it as connected/paired. Also make sure")
            print("  the ESP32 board is not currently connected to the same controller.")
            log_fh.close()
            return 3

        def on_notify(sender, data: bytearray):
            record(bytes(data), sender=sender)

        subscribed = []
        for ch in chars:
            print(f"  subscribing to {ch.uuid} handle={ch.handle} ...")
            try:
                await asyncio.wait_for(client.start_notify(ch, on_notify), timeout=8.0)
                subscribed.append(ch)
                print(f"  subscribed to {ch.uuid} handle={ch.handle}")
            except asyncio.TimeoutError:
                print(f"  subscribe timed out for handle={ch.handle}; skipping this char")
            except Exception as e:
                print(f"  subscribe failed for handle={ch.handle}: {e!r}; skipping this char")
        chars = subscribed
        if not chars:
            print("  FATAL: none of the candidate notify characteristics could be subscribed.")
            log_fh.close()
            return 4
        print("  --- HID reports will start streaming below ---")
        sys.stdout.flush()
        await asyncio.sleep(0.5)

        # ---- PHASE 3: IDLE (5 s baseline, but with a "ready" confirm) -
        current_phase[0] = PHASE_DEFS[2][0]
        print(f"\n[{current_phase[0]}] {PHASE_DEFS[2][1]}")
        print(f"  Recording baseline for {args.idle_seconds:.0f} seconds...")
        await asyncio.sleep(args.idle_seconds)
        print(f"  IDLE done. Press Enter to continue.")
        confirm("> ")

        # ---- PHASES 4..13: each one waits for the user ---------------
        for i in range(3, len(PHASE_DEFS) - 1):  # skip DONE
            name, prompt = PHASE_DEFS[i]
            current_phase[0] = name
            print(f"\n[{name}]")
            print(f"  {prompt}")
            print(f"  (Doing the action now. Press Enter when you've finished to advance.)")
            sys.stdout.flush()
            confirm("> ")
            # brief settle so the button release reports land before the next prompt
            await asyncio.sleep(0.5)
    finally:
        for ch in chars:
            try:
                await client.stop_notify(ch)
            except Exception:
                pass
        try:
            await client.disconnect()
        except Exception:
            pass

    log_fh.close()

    # ---- PHASE 14: SUMMARY --------------------------------------------
    current_phase[0] = PHASE_DEFS[-1][0]
    print(f"\n[{current_phase[0]}] {PHASE_DEFS[-1][1]}")

    counts: Counter[str] = Counter()
    per_phase: dict[str, dict] = {}
    for r in state["all_reports"]:
        if r["decoded"]:
            for k, v in r["decoded"]["buttons_decoded"].items():
                if v:
                    counts[f"buttons.{k}"] += 1
            counts[f"dpad.{r['decoded']['dpad_decoded']}"] += 1
            p = per_phase.setdefault(
                r["phase"], {"min": {}, "max": {}, "samples": 0}
            )
            p["samples"] += 1
            for axis in ("lx", "ly", "rx", "ry", "lt", "rt"):
                v = r["decoded"][axis]
                p["min"][axis] = min(p["min"].get(axis, v), v)
                p["max"][axis] = max(p["max"].get(axis, v), v)

    summary = {
        "log_file": str(jsonl_path),
        "report_count": state["report_count"],
        "connected_address": state["connected_address"],
        "button_seen":   {k.split(".", 1)[1]: v for k, v in counts.items() if k.startswith("buttons.")},
        "dpad_seen":     {k.split(".", 1)[1]: v for k, v in counts.items() if k.startswith("dpad.")},
        "per_phase_extremes": per_phase,
        "phases_completed": [n for n, _ in PHASE_DEFS],
        "raw_layout_assumed": (
            "Byte0..3: LX,LY,RX,RY (0..255, center 127). "
            "Byte4: A=1,B=2,X=4,Y=8,L1=0x10,R1=0x20,L2=0x40,R2=0x80. "
            "Byte5: SELECT=1,START=2,L3=4,R3=8,HOME=0x10. "
            "Byte6..7: LT,RT (0..255). Byte8: dpad hat (0..7=N..NW, 8=center)."
        ),
    }
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"  summary -> {summary_path}")
    print(f"  total reports: {summary['report_count']}")
    print(f"  buttons seen:  {summary['button_seen']}")
    print(f"  dpad seen:     {summary['dpad_seen']}")
    if "IDLE" in per_phase:
        idle = per_phase["IDLE"]
        print("\n  IDLE-phase axis ranges (at-rest bytes):")
        for axis in ("lx", "ly", "rx", "ry", "lt", "rt"):
            print(f"    {axis}: min={idle['min'].get(axis)}  max={idle['max'].get(axis)}")
    print(f"\nDone. Inspect {jsonl_path.name} for the full byte stream.")
    print("Paste the .summary.json back to me and I'll patch the firmware parser.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run()))
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(1)