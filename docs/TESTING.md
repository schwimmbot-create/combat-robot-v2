# Testing on Hardware

This document is the manual test plan for combat robot v2. **It is not optional** — the BLE layer, in particular, has not been tested against any specific 8BitDo model, and there are several known unknowns.

## Before you start — run the host test suite

```bash
pip install -r tests/requirements.txt
pytest tests/
# or
bash tests/pre_flash_check.sh
```

If a test fails (especially the schematic pinout check), **resolve it before flashing**. The tests are designed to catch the kinds of regressions that would silently break a combat robot mid-fight.

Current state: **256 tests pass, 4 skipped** (most skips are intentional-modification skips in `tests/regression/test_structure.py`). Run in <1 s after the first run.

## Required hardware

- ESP32-C3 DevKit M02 (or your target board)
- USB cable (data + power)
- 8BitDo controller in BLE mode (or compatible BLE HID gamepad)
- A serial monitor (Arduino Serial Monitor, `pio device monitor`, or PuTTY)
- (Optional) A WiFi device (phone/laptop) to test the web UI

## First boot

1. Flash the firmware: `pio run -e esp32-c3-devkitc-02 -t upload`
2. Open a serial monitor at 115200 baud.
3. Watch the boot logs. You should see:
   ```
   Combat Robot v2 booting
   ...
   Robot Firmware: Version 1.3
   BLE stack: NimBLE (replaces Bluepad32)
   ...
   No paired controllers — entering pairing mode
   ...
   Initializing web config
   Trying saved WiFi: <no saved creds>
   No saved WiFi credentials, will start AP
   Started AP: Combat-Robot-XXXX (password: fightbot), IP: 192.168.4.1
   Web server started on port 80
   ```
4. Note the AP name and IP. The default password is `fightbot` — **change this before deploying**.

## Test 1: Web UI loads

1. Connect your phone/laptop to the `Combat-Robot-XXXX` WiFi.
2. Open `http://192.168.4.1/` in a browser.
3. The dashboard should load with status, controller, paired list, WiFi, firmware sections.
4. **Expected:** all sections visible, no console errors in the browser dev tools.

## Test 2: Pairing via web UI

1. Put your 8BitDo into pairing mode (usually hold a button until LED flashes).
2. On the web UI, click "Enter Pairing Mode".
3. Within 60 seconds, the controller should pair and the LED strip should change.
4. **Expected:** "Connected: ✅" appears on the dashboard. The paired list shows your controller's MAC.

**Log on the robot side should show:**
```
Connected to XX:XX:XX:XX:XX:XX
Added to whitelist
Found svc 0x1812, handle range XXXX..XXXX
Found HID input report chr, val_handle=XXXX
Subscribe complete; status=0
```

## Test 3: Robot responds to input

Default mapping (configurable via the Outputs tab in the web UI):

| Output | Default source | Direction |
|---|---|---|
| M1 (drive motor 1) | LY (left stick Y) | normal |
| M2 (drive motor 2) | LY (left stick Y) | normal |
| S1/S2 aux role | user configured (for example ESC / motor controller on S1 or S2 with RT and Safety-critical weapon role enabled) | normal / polarity per role |

With the controller paired:

1. Move the left stick → drive wheels should respond.
2. If S1 or S2 is configured as `esc` with RT as its source and Safety-critical weapon role enabled, pull the right trigger → that aux ESC should spin up.
3. Verify the configuration by opening the Outputs tab on `http://192.168.4.1/` — the dropdowns should reflect the above mapping.

To remap M1 to a different source (e.g. RX for tank steering):

1. Open the Outputs tab.
2. Change M1's primary dropdown to RX.
3. Click **Save changes** at the bottom.
4. Move the right stick X — M1 should respond.

Saved changes persist in NVS (`output_cfg/cfg_v1` blob).

## Test 4: Re-pairing after disconnect

1. With controller paired, turn the controller off.
2. Verify the robot's LED strip turns blue (controller timeout).
3. Click "Enter Pairing Mode" on the web UI.
4. Turn the controller back on. It should re-pair automatically within 5 seconds.

**This is the test for the original v1.3 bug** ("controller dies mid-fight, can't reconnect without reset"). It must work.

## Test 5: Whitelist enforcement

1. With one controller paired, try to pair a different controller.
2. The new controller should be rejected (connection drops, no added to whitelist).

## Test 6: Clear whitelist

1. Click "Clear Paired Controllers" on the web UI. Confirm.
2. The robot should re-enter pairing mode.
3. Any controller can now connect.

## Test 7: WiFi STA mode

1. POST to `/api/wifi` with body `{"ssid":"MyHomeWiFi","psk":"mypassword"}`.
2. Restart the robot.
3. The robot should connect to your home WiFi and start a web server on the assigned IP.

## Test 8: WebSocket live feed

1. Connect to the AP, open `http://192.168.4.1/` in a browser.
2. Open browser developer tools → Console. With no controller connected, no `ws open` / `ws close` should appear at all (no clients means no spam).
3. Pair a controller. Within ~1 second the page should show the live stick canvas, LT/RT bars, and button chips reacting to your inputs.
4. Console: `ws open` is expected on connect, `ws close` only if you navigate away.

Implemented as `AsyncWebSocket` mounted at `/ws`. See `components/web_config/src/web_config.cpp::gamepad_ws_tick()` for the streaming logic.

## Test 9: Captive portal

1. Connect to the AP, leave the network settings for ~10 seconds.
2. Android: you should see a "Sign in to network" notification.
3. iOS: any browser attempt to load a URL should auto-redirect to `http://192.168.4.1/`.
4. Captive-portal probe hosts (`connectivitycheck.gstatic.com`, `captive.apple.com`, etc.) should all resolve to the AP IP (`192.168.4.1`).

DNS handled by `DNSServer` on port 53 in `web_config.cpp::start_ap_mode()`.

## Known unknowns

- **8BitDo model HID descriptor.** We assume the standard Bluetooth HID gamepad layout (X/Y/Z/Rz axes, 16-bit button mask, 2 trigger bytes, hat switch). The 8BitDo Ultimate and Pro 2 in BLE mode both follow this, but the exact axis order (which axis is left stick X vs Y) may differ between models. If axes are swapped, fix `parse_hid_report()` in `ble_gamepad.cpp`.
- **Hat switch byte order.** Some controllers report hat as 0=center and 8=N; others report 8=center and 15=released. The current code handles both, but verify with serial logs.
- **Connection interval.** Some 8BitDo models negotiate to 30ms connection interval by default. The code requests 7.5-15ms; the controller may not honor that. Use `ble_gap_update_params` if you need to renegotiate.
- **Bonding.** Currently we whitelist by MAC only — we don't enforce re-bonding (so a controller that was previously paired will auto-reconnect). That's intentional for combat-robot use, but be aware.
- **Battery level reporting.** Many BLE gamepads report battery via the Battery service (0x180f). Not currently parsed. Easy to add — see `decode_battery_service()` in `ble_gamepad.cpp` (TODO marker).

## Reporting bugs

When reporting a test failure, please include:
- Serial monitor output (full boot log + the failing interaction).
- The 8BitDo model and firmware version.
- The board you're using.
- What you expected vs what happened.

Without this info, debugging BLE issues is impossible.