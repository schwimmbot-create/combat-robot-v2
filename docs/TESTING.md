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

1. With controller paired, move the left stick. You should see the drive wheels respond (or not, if you haven't calibrated).
2. Press triggers — drum should spin up.
3. Press Y button — orientation should flip (per existing processButtons logic).

**Log should show:**
```
DriveMotor Forward: 200
ESC Duty Cycle: 150    ESC Pulse Width: 188 uSec
```

If you see no motor response, check:
- `processControllers()` is being called (add an `ESP_LOGI` in `loop()`).
- The axes from your 8BitDo are not all zero (verify by serial-printing `controllerState`).
- The `parse_hid_report` function is being called (add an `ESP_LOGD` in the `BLE_GAP_EVENT_NOTIFY_RX` case).

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

1. POST to `/api/wifi` with `{"ssid":"MyHomeWiFi","psk":"mypassword"}`.
2. Restart the robot.
3. The robot should connect to your home WiFi and start a web server on the assigned IP.

(Currently, there's no UI form for this — it's a JSON API. A form is in Phase 2.)

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