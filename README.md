# Combat Robot v2

Firmware rewrite of `schwimmflugel/esp-idf-arduino-bluepad32-template`'s `combat_robot` branch. Replaces Bluepad32 with a NimBLE-based standard HID gamepad parser, adds an async web UI for configuration, and sets up the architecture for runtime motor/pin/LED configuration.

## What's in here

- `main/` — `app_main` + Arduino `setup()`/`loop()`
- `components/myrobot/` — ported from v1.3 (Drive, Drum, TaskManager, PowerFunctions, etc.)
- `components/ble_gamepad/` — **NEW** NimBLE-based BLE HID gamepad parser with NVS whitelist
- `components/web_config/` — **NEW** ESPAsyncWebServer with HTML dashboard, OTA, WiFi manager
- `docs/DECISIONS.md` — why we made each decision (read this first)
- `docs/BUILD.md` — how to compile and flash
- `docs/TESTING.md` — manual test plan (must run before deploying)

## Quick start

```bash
# Build
pio run -e esp32-c3-devkitc-02

# Flash (hold BOOT button while it connects)
pio run -e esp32-c3-devkitc-02 -t upload

# Serial monitor
pio device monitor -e esp32-c3-devkitc-02
```

## Current status (first cut)

| Feature | Status |
|---|---|
| Boot | ✅ Compiles, no runtime test yet |
| BLE scanning | ✅ Implemented, untested on hardware |
| BLE pairing + HID parsing | ✅ Implemented, untested on hardware |
| NVS MAC whitelist | ✅ Implemented, untested on hardware |
| Web UI dashboard | ✅ Implemented, untested on hardware |
| OTA upload endpoint | ✅ Implemented, untested on hardware |
| WiFi STA+AP fallback | ✅ Implemented, untested on hardware |
| NVS board rev override | ✅ Implemented, untested on hardware |
| Captive portal DNS | ⏳ TODO |
| Pairing button (GPIO) | ⏳ Stub (web UI works) |
| Motor/pin config via web | ⏳ Phase 2 |
| Input mapping editor | ⏳ Phase 2 |
| LED effect library | ⏳ Phase 2 |

**Bottom line:** The PC toolchain and ESP32-C3 flashing path are verified with a minimal ESP-IDF heartbeat app on COM6. The full robot firmware is not yet hardware-verified, and the current `partitions.csv` is too large for the 4MB ESP32-C3 target. See `docs/BUILD.md` for the exact build/flash commands and current blocker.

See `tests/README.md` for what's covered.

## Test status

**216 tests pass, 0 fail** (host-side pytest). Run with:

```bash
pip install -r tests/requirements.txt
pytest tests/
```

Or use the pre-flash gate:

```bash
bash tests/pre_flash_check.sh
```

- `docs/DECISIONS.md` — the architecture decisions
- `docs/TESTING.md` — what to test and how