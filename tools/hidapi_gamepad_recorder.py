#!/usr/bin/env python3
"""
hidapi_gamepad_recorder.py - Windows HIDAPI recorder for paired gamepads.

Use this when Windows has paired the controller and exposes it as a HID gamepad
but BLE GATT notifications do not arrive through bleak. The 8BitDo Ultimate 2
Wireless shows up this way on Windows:

  usage_page=1, usage=5, product_string='8BitDo Ultimate 2 Wireless'

The script opens the HID device, starts a background reader thread, then walks
the user through physical input phases. Every HID input report is logged as
JSONL with the active phase label.

Run:
  python tools/hidapi_gamepad_recorder.py --list
  python tools/hidapi_gamepad_recorder.py

Phase advance is manual: press Enter to move on; q+Enter aborts cleanly.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import hid

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = SCRIPT_DIR / "ble_recordings"
LOG_DIR.mkdir(parents=True, exist_ok=True)

PHASE_DEFS = [
    ("IDLE", "Don't touch the controller. Capturing a 5-second baseline."),
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
]


def make_log_paths() -> tuple[Path, Path, Path]:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return (
        LOG_DIR / f"hidapi-{stamp}.jsonl",
        LOG_DIR / f"hidapi-{stamp}.console.log",
        LOG_DIR / f"hidapi-{stamp}.summary.json",
    )


def _clean(v):
    if isinstance(v, bytes):
        return v.decode("latin1", "ignore")
    return v


def enumerate_gamepads() -> list[dict]:
    out = []
    for d in hid.enumerate():
        product = str(_clean(d.get("product_string", "")) or "")
        manufacturer = str(_clean(d.get("manufacturer_string", "")) or "")
        path = _clean(d.get("path"))
        usage_page = d.get("usage_page")
        usage = d.get("usage")
        text = f"{manufacturer} {product} {path}".lower()
        is_gamepad = usage_page == 1 and usage in (4, 5)
        is_8bitdo = "8bitdo" in text or "ultimate" in text
        if is_gamepad or is_8bitdo:
            dd = {k: _clean(v) for k, v in d.items()}
            dd["_score"] = (100 if is_8bitdo else 0) + (10 if is_gamepad else 0)
            out.append(dd)
    out.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return out


def print_devices(devices: list[dict]) -> None:
    if not devices:
        print("No HID gamepad-like devices found.")
        return
    for i, d in enumerate(devices):
        print(f"[{i}] vid={d.get('vendor_id'):04x} pid={d.get('product_id'):04x} "
              f"usage_page={d.get('usage_page')} usage={d.get('usage')} bus={d.get('bus_type')}")
        print(f"    manufacturer={d.get('manufacturer_string')!r}")
        print(f"    product     ={d.get('product_string')!r}")
        print(f"    serial      ={d.get('serial_number')!r}")
        print(f"    path        ={d.get('path')!r}")


def open_hid_path(path):
    dev = hid.device()
    # hidapi usually returns bytes paths on Windows; tolerate str from JSON/debug.
    dev.open_path(path.encode("latin1") if isinstance(path, str) else path)
    dev.set_nonblocking(True)
    return dev


def decode_candidate(buf: bytes, offset: int = 0) -> dict | None:
    """Candidate standard gamepad decode starting at offset.

    HIDAPI often includes a leading report ID byte. We decode both offset=0
    and offset=1 so the captured data can tell us which one is meaningful.
    """
    if len(buf) < offset + 9:
        return None
    data = buf[offset:offset + 9]
    return {
        "offset": offset,
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
            "L2_DIGITAL": bool(data[4] & 0x40),
            "R2_DIGITAL": bool(data[4] & 0x80),
            "SELECT": bool(data[5] & 0x01),
            "START": bool(data[5] & 0x02),
            "L3": bool(data[5] & 0x04),
            "R3": bool(data[5] & 0x08),
            "HOME": bool(data[5] & 0x10),
        },
        "dpad_decoded": {
            0: "N", 1: "NE", 2: "E", 3: "SE", 4: "S",
            5: "SW", 6: "W", 7: "NW", 8: "center", 15: "released",
        }.get(data[8], f"0x{data[8]:02x}"),
    }


def decode_8bitdo_windows(buf: bytes) -> dict | None:
    """8BitDo Ultimate 2 as exposed by Windows HIDAPI.

    Observed idle report starts:
      01 0f 7f 7f 7f 7f 00 00 00 00 ...

    That is:
      byte0 = report id (0x01)
      byte1 = hat/dpad (0x0f at rest/released)
      byte2..5 = LX, LY, RX, RY (0..255, center 0x7f)
      byte6..7 = candidate buttons bitmask, little-endian
      byte8..9 = candidate LT/RT analog trigger bytes
    """
    if len(buf) < 10:
        return None
    buttons_low = buf[6]
    buttons_high = buf[7]
    dpad_raw = buf[1]
    return {
        "layout": "8bitdo_windows_hidapi_v1",
        "report_id": buf[0],
        "dpad": dpad_raw,
        "dpad_decoded": {
            0: "N", 1: "NE", 2: "E", 3: "SE", 4: "S",
            5: "SW", 6: "W", 7: "NW", 8: "center", 15: "released",
        }.get(dpad_raw, f"0x{dpad_raw:02x}"),
        "lx": buf[2],
        "ly": buf[3],
        "rx": buf[4],
        "ry": buf[5],
        "buttons_low": buttons_low,
        "buttons_high": buttons_high,
        "lt": buf[8],
        "rt": buf[9],
        "buttons_decoded": {
            "A": bool(buttons_low & 0x01),
            "B": bool(buttons_low & 0x02),
            "X": bool(buttons_low & 0x04),
            "Y": bool(buttons_low & 0x08),
            "L1": bool(buttons_low & 0x10),
            "R1": bool(buttons_low & 0x20),
            "L2_DIGITAL": bool(buttons_low & 0x40),
            "R2_DIGITAL": bool(buttons_low & 0x80),
            "SELECT": bool(buttons_high & 0x01),
            "START": bool(buttons_high & 0x02),
            "L3": bool(buttons_high & 0x04),
            "R3": bool(buttons_high & 0x08),
            "HOME": bool(buttons_high & 0x10),
        },
    }


def decode_report(buf: bytes) -> dict:
    return {
        "8bitdo_windows": decode_8bitdo_windows(buf),
        "offset0": decode_candidate(buf, 0),
        "offset1": decode_candidate(buf, 1),
    }


def confirm(prompt: str) -> None:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line = sys.stdin.readline()
    if line.strip().lower() in {"q", "quit", "exit", "x"}:
        raise KeyboardInterrupt


def summarize(reports: list[dict], summary_path: Path, log_path: Path,
              console_log_path: Path, device: dict) -> None:
    per_phase = {}
    buttons = Counter()
    dpad = Counter()
    lengths = Counter()

    for r in reports:
        lengths[r["len"]] += 1
        for key in ("8bitdo_windows", "offset0", "offset1"):
            d = r["decoded"].get(key)
            if not d:
                continue
            phase_key = f"{r['phase']}:{key}"
            p = per_phase.setdefault(phase_key, {"samples": 0, "min": {}, "max": {}})
            p["samples"] += 1
            for axis in ("lx", "ly", "rx", "ry", "lt", "rt", "dpad", "buttons_low", "buttons_high"):
                v = d[axis]
                p["min"][axis] = min(p["min"].get(axis, v), v)
                p["max"][axis] = max(p["max"].get(axis, v), v)
            for name, on in d["buttons_decoded"].items():
                if on:
                    buttons[f"{key}.{name}"] += 1
            dpad[f"{key}.{d['dpad_decoded']}"] += 1

    summary = {
        "transport": "hidapi",
        "log_file": str(log_path),
        "console_log_file": str(console_log_path),
        "report_count": len(reports),
        "report_lengths": dict(lengths),
        "device": {k: v for k, v in device.items() if not k.startswith("_")},
        "button_seen": dict(buttons),
        "dpad_seen": dict(dpad),
        "per_phase_extremes": per_phase,
        "decoder_note": "8bitdo_windows is the observed Windows HIDAPI layout: byte0 report id, byte1 hat/dpad, byte2..5 axes, byte6..7 buttons, byte8..9 triggers. offset0/offset1 are retained as raw candidate decodes for comparison.",
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"summary -> {summary_path}")
    print(f"reports -> {len(reports)}")
    print(f"lengths -> {dict(lengths)}")
    print(f"buttons -> {dict(buttons)}")
    print(f"dpad    -> {dict(dpad)}")


def run() -> int:
    parser = argparse.ArgumentParser(description="HIDAPI paired-gamepad recorder")
    parser.add_argument("--list", action="store_true", help="list candidate HID gamepads and exit")
    parser.add_argument("--device-index", type=int, default=0, help="candidate device index from --list")
    parser.add_argument("--read-len", type=int, default=64, help="HID read length")
    parser.add_argument("--idle-seconds", type=float, default=5.0, help="baseline capture seconds")
    parser.add_argument("--verbose", action="store_true",
                        help="also print every HID report to the terminal; reports always go to .console.log")
    args = parser.parse_args()

    devices = enumerate_gamepads()
    if args.list:
        print_devices(devices)
        return 0
    if not devices:
        print("No candidate HID gamepads found. Pair/connect the controller in Windows first.")
        return 2
    if args.device_index < 0 or args.device_index >= len(devices):
        print_devices(devices)
        print(f"Invalid --device-index {args.device_index}")
        return 2

    device = devices[args.device_index]
    print("Using HID device:")
    print_devices([device])
    log_path, console_log_path, summary_path = make_log_paths()
    print(f"JSONL log to:   {log_path}")
    print(f"Console log to: {console_log_path}")
    print(f"Summary to:     {summary_path}")
    print("Type q + Enter at any prompt to abort cleanly.")
    print()

    dev = open_hid_path(device["path"])
    reports: list[dict] = []
    current_phase = ["IDLE"]
    running = [True]
    lock = threading.Lock()
    seq = [0]

    log_fh = log_path.open("w", encoding="utf-8")
    console_fh = console_log_path.open("w", encoding="utf-8")
    console_fh.write(f"Using HID device: {device.get('product_string')!r} serial={device.get('serial_number')!r}\n")
    console_fh.write(f"JSONL log: {log_path}\n")
    console_fh.write(f"Summary: {summary_path}\n\n")
    console_fh.flush()

    def reader() -> None:
        while running[0]:
            try:
                data = dev.read(args.read_len)
            except Exception as e:
                print(f"reader error: {e!r}")
                time.sleep(0.1)
                continue
            if not data:
                time.sleep(0.005)
                continue
            raw = bytes(data)
            with lock:
                seq[0] += 1
                entry = {
                    "ts": time.time(),
                    "iso": dt.datetime.now().isoformat(timespec="milliseconds"),
                    "phase": current_phase[0],
                    "seq": seq[0],
                    "raw_hex": raw.hex(),
                    "len": len(raw),
                    "decoded": decode_report(raw),
                }
                reports.append(entry)
                log_fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
                log_fh.flush()
            d8 = entry["decoded"].get("8bitdo_windows")
            d0 = entry["decoded"].get("offset0")
            d1 = entry["decoded"].get("offset1")
            d = d8 or d1 or d0
            if d:
                btns = ",".join(k for k, v in d["buttons_decoded"].items() if v) or "-"
                line = (f"  [{entry['phase']:>18}] seq={entry['seq']:>5} len={entry['len']:<2} "
                        f"raw={entry['raw_hex'][:32]:<32} "
                        f"LX={d['lx']:<3} LY={d['ly']:<3} RX={d['rx']:<3} RY={d['ry']:<3} "
                        f"LT={d['lt']:<3} RT={d['rt']:<3} dpad={d['dpad_decoded']:<8} btns={btns}")
            else:
                line = f"  [{entry['phase']:>18}] seq={entry['seq']:>5} len={entry['len']:<2} raw={entry['raw_hex']}"
            console_fh.write(line + "\n")
            console_fh.flush()
            if args.verbose:
                print(line)

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    try:
        phase, prompt = PHASE_DEFS[0]
        current_phase[0] = phase
        console_fh.write(f"\n[{phase}] {prompt}\n")
        console_fh.flush()
        print(f"[{phase}] {prompt}")
        print(f"Recording baseline for {args.idle_seconds:.0f}s...")
        time.sleep(args.idle_seconds)
        confirm("Baseline done. Press Enter to continue.\n> ")

        for phase, prompt in PHASE_DEFS[1:]:
            current_phase[0] = phase
            print(f"\n[{phase}]\n  {prompt}")
            print("  Do the action now. Press Enter when finished.")
            confirm("> ")
            time.sleep(0.4)
    except KeyboardInterrupt:
        print("\nAborted by user; writing summary for captured reports.")
    finally:
        running[0] = False
        t.join(timeout=1.0)
        try:
            dev.close()
        except Exception:
            pass
        log_fh.close()
        console_fh.close()

    summarize(reports, summary_path, log_path, console_log_path, device)
    print("Paste the .summary.json back to me and I’ll patch the firmware parser.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
