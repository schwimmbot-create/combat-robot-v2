#!/usr/bin/env python
"""PC Bluetooth bench helper for combat-robot-v2.

Uses the PC's BLE adapter via bleak to scan, connect, subscribe to
notifications, and write test payloads. This is intended for two workflows:

1. Drive the robot's board-side bench GATT service by writing synthetic
   controller frames to its writable characteristic. This is the default
   for the `write` command.
2. Inspect real BLE gamepads from the PC (scan + optional notify if the
   OS allows connecting to the device's exposed GATT services).
3. Drive any other firmware bench-test GATT service by overriding the
   characteristic UUID.

Important Windows limitation: bleak is a BLE central/client library. It does
not make Windows advertise as a BLE HID peripheral, so it cannot directly
pretend to be a gamepad to firmware that only scans for HID peripherals.
"""

from __future__ import annotations

import argparse
import asyncio
import binascii
import sys
from dataclasses import dataclass
from typing import Iterable

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # pragma: no cover - exercised manually on dev PCs
    BleakClient = None
    BleakScanner = None


def require_bleak():
    if BleakClient is None or BleakScanner is None:
        raise SystemExit("Missing dependency: bleak. Install with: python -m pip install -r tools/requirements-pc-ble.txt")


HID_SERVICE_UUID = "00001812-0000-1000-8000-00805f9b34fb"
HID_REPORT_UUID = "00002a4d-0000-1000-8000-00805f9b34fb"
BOARD_BENCH_SERVICE_UUID = "7d2f0001-0f3a-4b8a-9b7d-2f4c9a000001"
BOARD_BENCH_WRITE_UUID = "7d2f0002-0f3a-4b8a-9b7d-2f4c9a000001"
DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class HidFrame:
    """Standard-ish 9-byte BLE HID gamepad report used by our firmware parser."""

    lx: int = 127
    ly: int = 127
    rx: int = 127
    ry: int = 127
    buttons: int = 0
    lt: int = 0
    rt: int = 0
    hat: int = 8

    def bytes(self) -> bytes:
        return bytes([
            self.lx & 0xFF,
            self.ly & 0xFF,
            self.rx & 0xFF,
            self.ry & 0xFF,
            self.buttons & 0xFF,
            (self.buttons >> 8) & 0xFF,
            self.lt & 0xFF,
            self.rt & 0xFF,
            self.hat & 0xFF,
        ])


@dataclass(frozen=True)
class EightBitDoFrame:
    """8BitDo Ultimate 2 report payload observed from BLE report handle 29.

    This is the no-report-id BLE HOGP shape:
    hat, LX, LY, RX, RY, R2, L2, buttons0, buttons1, ... padding.
    """

    lx: int = 127
    ly: int = 127
    rx: int = 127
    ry: int = 127
    r2: int = 0
    l2: int = 0
    buttons0: int = 0
    buttons1: int = 0
    hat: int = 15
    length: int = 33

    def bytes(self) -> bytes:
        core = bytes([
            self.hat & 0xFF,
            self.lx & 0xFF,
            self.ly & 0xFF,
            self.rx & 0xFF,
            self.ry & 0xFF,
            self.r2 & 0xFF,
            self.l2 & 0xFF,
            self.buttons0 & 0xFF,
            self.buttons1 & 0xFF,
        ])
        return core + bytes(max(0, self.length - len(core)))


def parse_hex_payload(text: str) -> bytes:
    cleaned = text.replace(" ", "").replace(":", "").replace("-", "")
    if len(cleaned) % 2:
        raise argparse.ArgumentTypeError("hex payload must have an even number of digits")
    try:
        return binascii.unhexlify(cleaned)
    except binascii.Error as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def print_devices(devices: Iterable):
    for dev in devices:
        name = dev.name or "<unnamed>"
        uuids = ",".join((dev.metadata or {}).get("uuids", []) or [])
        print(f"{dev.address:>20}  {name}  {uuids}")


async def scan(args: argparse.Namespace) -> int:
    require_bleak()
    devices = await BleakScanner.discover(timeout=args.timeout, return_adv=False)
    if args.hid_only:
        devices = [d for d in devices if HID_SERVICE_UUID.lower() in [u.lower() for u in (d.metadata or {}).get("uuids", [])]]
    if args.bench_only:
        devices = [d for d in devices if BOARD_BENCH_SERVICE_UUID.lower() in [u.lower() for u in (d.metadata or {}).get("uuids", [])]]
    print_devices(devices)
    return 0


async def notify(args: argparse.Namespace) -> int:
    require_bleak()
    def on_notify(sender, data: bytearray):
        print(f"notify {sender}: {bytes(data).hex(' ')}")

    async with BleakClient(args.address, timeout=args.timeout) as client:
        await client.start_notify(args.characteristic, on_notify)
        print(f"Subscribed to {args.characteristic}; press Ctrl+C to stop")
        await asyncio.sleep(args.duration)
        await client.stop_notify(args.characteristic)
    return 0


async def write(args: argparse.Namespace) -> int:
    require_bleak()
    payload = args.payload
    if args.standard_frame:
        payload = HidFrame(
            lx=args.lx,
            ly=args.ly,
            rx=args.rx,
            ry=args.ry,
            buttons=args.buttons,
            lt=args.lt,
            rt=args.rt,
            hat=args.hat,
        ).bytes()
    if args.eightbitdo_frame:
        payload = EightBitDoFrame(
            lx=args.lx,
            ly=args.ly,
            rx=args.rx,
            ry=args.ry,
            r2=args.r2,
            l2=args.l2,
            buttons0=args.buttons0,
            buttons1=args.buttons1,
            hat=args.hat,
            length=args.length,
        ).bytes()

    async with BleakClient(args.address, timeout=args.timeout) as client:
        await client.write_gatt_char(args.characteristic, payload, response=args.response)
        print(f"wrote {len(payload)} bytes to {args.characteristic}: {payload.hex(' ')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.set_defaults(func=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="scan for BLE devices")
    p_scan.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p_scan.add_argument("--hid-only", action="store_true", help="show devices advertising HID service UUID 0x1812")
    p_scan.add_argument("--bench-only", action="store_true", help="show devices advertising combat-robot-v2 bench service")
    p_scan.set_defaults(func=scan)

    p_notify = sub.add_parser("notify", help="subscribe to a characteristic")
    p_notify.add_argument("address")
    p_notify.add_argument("--characteristic", default=HID_REPORT_UUID)
    p_notify.add_argument("--duration", type=float, default=30.0)
    p_notify.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p_notify.set_defaults(func=notify)

    p_write = sub.add_parser("write", help="write raw or synthetic HID-report bytes")
    p_write.add_argument("address")
    p_write.add_argument("--characteristic", default=BOARD_BENCH_WRITE_UUID)
    p_write.add_argument("--payload", type=parse_hex_payload, default=b"7f7f7f7f0000000008")
    p_write.add_argument("--response", action="store_true")
    p_write.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p_write.add_argument("--standard-frame", action="store_true", help="build a 9-byte standard HID frame from fields below")
    p_write.add_argument("--eightbitdo-frame", action="store_true", help="build a 33-byte 8BitDo Ultimate 2 BLE report payload")
    p_write.add_argument("--lx", type=int, default=127)
    p_write.add_argument("--ly", type=int, default=127)
    p_write.add_argument("--rx", type=int, default=127)
    p_write.add_argument("--ry", type=int, default=127)
    p_write.add_argument("--buttons", type=lambda x: int(x, 0), default=0)
    p_write.add_argument("--buttons0", type=lambda x: int(x, 0), default=0)
    p_write.add_argument("--buttons1", type=lambda x: int(x, 0), default=0)
    p_write.add_argument("--lt", type=int, default=0)
    p_write.add_argument("--rt", type=int, default=0)
    p_write.add_argument("--l2", type=int, default=0)
    p_write.add_argument("--r2", type=int, default=0)
    p_write.add_argument("--hat", type=int, default=8)
    p_write.add_argument("--length", type=int, default=33)
    p_write.set_defaults(func=write)

    return parser


async def amain(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return await args.func(args)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(amain(argv))


if __name__ == "__main__":
    raise SystemExit(main())
