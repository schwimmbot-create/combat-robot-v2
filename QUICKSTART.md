# Combat Robot v2 — cross-platform quickstart

ESP32-C3 BLE combat-robot controller: NimBLE host for the 8BitDo controller,
`myrobot` drive/drum/task pipeline, and a mobile web UI for REST/WebSocket
configuration.

- **Upstream:** <https://github.com/schwimmbot-create/combat-robot-v2>
- **Primary firmware env:** `esp32-c3-devkitc-02`
- **Dev firmware env:** `esp32-c3-devkitc-02-dev` (`BENCH_HID_PUBLIC=1`)

## One command surface for Linux / macOS / Windows

Use Python directly everywhere:

```bash
python tools/dev.py setup
python tools/dev.py test
python tools/dev.py build --env esp32-c3-devkitc-02-dev
python tools/dev.py flash --env esp32-c3-devkitc-02-dev --port COM6
python tools/dev.py monitor --port COM6
```

On Windows, run those from Git Bash, Windows Terminal, PowerShell, or cmd from
the repo root. If your launcher is `py` instead of `python`, use:

```powershell
py -3 tools/dev.py setup
py -3 tools/dev.py flash --env esp32-c3-devkitc-02-dev --port COM6
```

If you have `make`, the Makefile is just a thin wrapper around the same script:

```bash
make setup
make test
make build ENV=esp32-c3-devkitc-02-dev
make flash ENV=esp32-c3-devkitc-02-dev PORT=COM6
make monitor PORT=COM6
```

## Setup

```bash
cd path/to/combat-robot-v2
python tools/dev.py setup
```

`setup` creates `.venv/` and installs:

- PlatformIO
- pytest
- bleak

It uses `uv` when available, otherwise falls back to Python's built-in `venv` +
`pip`. ESP32 toolchains are downloaded by PlatformIO on the first build.

Check what the wrapper detected:

```bash
python tools/dev.py info
```

## Serial ports by OS

Defaults are intentionally simple and overrideable:

| OS | Default port | Typical alternatives |
|---|---|---|
| Windows | `COM6` | `COM3`, `COM4`, Device Manager → Ports |
| Linux | `/dev/ttyACM0` | `/dev/ttyACM1`, `/dev/ttyUSB0` |
| macOS | `/dev/cu.usbmodem1101` | `/dev/cu.usbserial-*`, `/dev/cu.usbmodem*` |

Override the port every time if needed:

```bash
python tools/dev.py flash --port COM9
python tools/dev.py monitor --port /dev/ttyACM1
python tools/dev.py flash --port /dev/cu.usbmodem2101
```

## Fast loop

```bash
# Static/unit/integration tests, no hardware needed
python tools/dev.py test

# Build firmware
python tools/dev.py build --env esp32-c3-devkitc-02-dev

# Flash board
python tools/dev.py flash --env esp32-c3-devkitc-02-dev --port COM6

# Serial monitor. Close this before flashing again.
python tools/dev.py monitor --port COM6
```

The monitor holds RTS/DTR low to avoid spurious ESP32-C3 resets:

```text
--rts 0 --dtr 0 --no-reconnect
```

## Build environments

| Env | Board | Notes |
|---|---|---|
| `esp32-c3-devkitc-02` | ESP32-C3 DevKitM-1 | primary BLE-only target |
| `esp32-c3-devkitc-02-dev` | same board | dev build; public BLE bench service enabled |
| `esp32dev` | original ESP32 | legacy sanity check |
| `esp32-s3-devkitc-1` | ESP32-S3 | sibling-radio bench test |
| `esp32-c6-devkitc-1` | ESP32-C6 | 802.15.4 sibling |
| `esp32-h2-devkitm-1` | ESP32-H2 | Thread/Zigbee sibling |

## BLE bench / mock input

```bash
# Scan for BLE devices / CombatRobot-v2
python tools/dev.py bench-scan

# Write a neutral synthetic HID frame
python tools/dev.py bench-write --mac AA:BB:CC:DD:EE:FF
```

Full bench CLI remains available:

```bash
python tools/pc_ble_bench.py --help
```

Mock robot drive simulator:

```bash
python tools/mock_robot_drive.py --mode arcade_split --ly -508 --rx 511
```

## Troubleshooting flash/monitor

- Close `monitor` before `flash`; only one process can own the serial port.
- If upload fails once, unplug/replug or tap reset/boot, then retry.
- Start with USB serial before chasing BLE/Wi-Fi. The ESP32-C3 may be alive even
  if the AP or BLE path is not reachable.
- After flashing, the robot AP should be reachable at:

```text
Combat-Robot-049D
http://192.168.4.1/
```
