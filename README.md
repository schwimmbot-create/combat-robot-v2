# Combat Robot v2

ESP32-C3 based combat robot controller. NimBLE for the BLE gamepad, an
async web UI for setup, and NVS-persistent per-output configuration for
the motor/servo channels.

## Hardware

- **MCU**: ESP32-C3-MINI-1-H4 (4 MB flash, **BLE only — no classic BT**).
- **Board rev 2** (current production): 2 × DRV8871 motor drivers (M1, M2),
  no drum output, 2 servo channels (S1, S2). Pin map and hardware notes in
  [`docs/BOARD_HARDWARE.md`](docs/BOARD_HARDWARE.md).
- **Board rev 3** is designed but not yet fabricated; the firmware
  supports it via `BOARD_REV=3` in `platformio.ini`.

## Repo layout

```
main/                       # app_main + Arduino setup()/loop()
  main.c                    # C entrypoint (calls Arduino setup via app_main)
  sketch.cpp                # Arduino-side start; pulls in components

components/
  myrobot/                  # v1.3 port: Drive, Drum, TaskManager, PowerFunctions
  board_config/             # pin map per BOARD_REV + BoardInfo struct
  ble_gamepad/              # NimBLE client; bench GATT service for PC tools
  output_config/            # NVS-backed per-output config (direction, source, deadzone)
  web_config/               # Async web server, REST endpoints, WebSocket, captive DNS

docs/
  config-ui-mockup.html     # source of the web UI (regenerated on every build)
  BOARD_HARDWARE.md         # full pin map + driver topology
  BUILD.md                  # exact build/flash commands
  TESTING.md                # pre-flash checklist + manual test plan
  DECISIONS.md              # why each architecture choice was made
  CHANGELOG.md              # shipped changes
  AGENT.md                  # ⭐ READ THIS if you're an AI/agent picking up this codebase

tools/
  gen_web_index.py          # Pre-build: embeds docs/config-ui-mockup.html as PROGMEM
  pc_ble_bench.py           # PC-side Bluetooth tool for bench testing (no gamepad)
  requirements-pc-ble.txt   # bleak + pygatt for pc_ble_bench.py
  build_and_flash.sh        # Local convenience: build + flash + monitor

tests/
  integration/test_*.py     # host-side pytest
  regression/test_structure.py

partitions.csv              # 4MB partition layout (nvs + phy + 2 app + storage)
platformio.ini              # PlatformIO project config
sdkconfig.defaults          # NimBLE-only ESP-IDF defaults
```

## Quick start

```bash
# Build (15 min the first time, ~15 s incremental after that)
pio run -e esp32-c3-devkitc-02

# Flash to the board on COM6 (board boots AP "Combat-Robot-<EFUSE>",
# password "fightbot")
pio run -e esp32-c3-devkitc-02 -t upload --upload-port COM6

# Serial monitor (add --rts 0 --dtr 0 to avoid spurious resets)
pio device monitor -p COM6 -b 115200 --rts 0 --dtr 0

# After flashing, join the robot's AP and open any URL — captive portal
# auto-redirects to the dashboard at http://192.168.4.1/
```

The full **per-feature** status and a list of what's still TODO is in
[`docs/BOARD_HARDWARE.md`](docs/BOARD_HARDWARE.md#status).

## Running tests

```bash
pip install pytest                # only pytest is needed (no other deps)
pytest tests/                     # 256 tests, ~1 s
```

Each pytest module checks the C source it covers against its documented
contract, so a passing `pytest` run is a strong proxy for "the firmware
is correctly wired" even on a workstation without a compiler. The same
test set is the source of `tests/integration/test_pre_flash.py`'s
"stop sign" gate.

## Authoritative guides for AI / agent work

- **Picking up the codebase → [`docs/AGENT.md`](docs/AGENT.md).**
  Architecture, build flags, hidden constraints (ESP32-C3 is BLE-only,
  AP password is `fightbot`, etc.), common pitfalls, and how to add a
  feature without breaking it.

- **Why a thing is the way it is → [`docs/DECISIONS.md`](docs/DECISIONS.md).**

- **Exact commands for build/flash/monitor → [`docs/BUILD.md`](docs/BUILD.md).**

- **What features are done / TODO → [`docs/BOARD_HARDWARE.md`](docs/BOARD_HARDWARE.md).**

## Status (as of commit 2fc6cc4)

| Feature | Status |
|---|---|
| Build (firmware 1.16 MB / Flash 69.1%) | ✅ |
| Flash to COM6 with hash-verified upload | ✅ |
| NimBLE scan + connect to standard HID gamepad | ✅ |
| 8BitDo Ultimate 2 HID parser | ✅ |
| NVS MAC whitelist (max 4 controllers) | ✅ |
| `output_config` component (5 outputs × 24 sources, NVS) | ✅ |
| REST: `GET/POST /api/config`, `GET /api/config/sources` | ✅ |
| WebSocket live feed at `/ws` (30 Hz, gated on controller connected) | ✅ |
| Captive portal DNS (port 53) | ✅ |
| Mobile-friendly tabbed web UI (Controller / Outputs / Settings / About) | ✅ |
| OTA `.bin` upload | ✅ |
| Apply config to motor/servo driver | ⏳ Not wired into `myrobot` yet |
| Battery mV reading on status card | ⏳ TODO in `PowerFunctions::getBatteryMillivolts` |
| LED effect library | ⏳ Phase 2 |
| v3 board pin map | ⏳ Defined in `board_config.h`, no fabricated board yet |
