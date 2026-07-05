# AGENT.md — Picking up Combat Robot v2

**Audience:** an AI/agent picking up this codebase cold, OR a human
returning after a long break. Read this before touching anything.

## TL;DR

- ESP32-C3 only (BLE-only radio). Anything talking about Xbox 360 / WiFi-Direct / classic-BT controllers will not work — full stop.
- All user-visible config (motor direction, input mapping, deadzone) lives in `components/output_config/` (NVS namespace `output_cfg`, blob key `cfg_v1`). The hardware config (pin assignments, board rev) lives in `components/board_config/` (compile-time `BOARD_REV`).
- The web UI is a single static HTML file at `docs/config-ui-mockup.html`, embedded into firmware flash by `tools/gen_web_index.py` as a `PROGMEM` raw-literal. **Edit the mockup, not the generated header.**
- The 8BitDo Ultimate 2 (and most "standard HID BLE gamepads") work out of the box. Xbox One + PS5 DualSense are NOT supported and need a separate parser.
- The robot ships an AP at boot (`Combat-Robot-<EFUSE>`, password `fightbot`) with a captive-portal DNS so any URL the user types redirects to `192.168.4.1`.
- Default input mapping: M1+M2 ← LY (left stick Y), Weapon ← RT, S1+S2 unassigned. Persisted in NVS as soon as the user clicks **Save changes** on the Outputs tab.

## File map — what to edit for what

| You want to… | Touch |
|---|---|
| Change web UI text, layout, or any visual behavior | `docs/config-ui-mockup.html` (the **single source**). The generator wraps it as a PROGMEM raw literal, no JS rewriting. |
| Add a new controller input source (e.g. `R2_ANALOG`) | Add the enum in `components/output_config/include/output_config.h`, update `kSourceNames[]` and `kSourceDisplayNames[]` in `components/output_config/src/output_config.c`, then add the matching entry to `SOURCES` in the mockup. |
| Add a new logical output (M3, etc.) | Same: extend `oc_output_id_t`, `kOutputIdStrings[]`, `kOutputDisplayNames[]`, `OUTPUTS[]` in the mockup, then run tests. |
| Change pin assignments | `components/board_config/include/board_config.h`. Compile-time `BOARD_REV`. `platformio.ini` currently has `-D BOARD_REV=2`. |
| Change the AP password | `components/web_config/src/web_config.cpp` — `AP_DEFAULT_PASSWORD` macro. |
| Change WiFi STA credentials at runtime | `api/wifi` POST endpoint (not yet implemented; the AP fallback is currently automatic). |
| Change battery cell count / low-voltage cutoff percent | `components/battery_config/` for NVS schema + validation, `components/myrobot/src/PowerFunctions.cpp` for runtime cutoff/percent math, `docs/config-ui-mockup.html` for Settings UI. |
| Add a new REST endpoint | `components/web_config/src/web_config.cpp::register_routes()`. JSON: use `output_config_to_json`-style hand-rolled writer for small payloads, or pull in ArduinoJson. |
| Add a new tab to the web UI | `docs/config-ui-mockup.html`: add `<button data-tab="X">` and a `<section class="panel" data-panel="X">`, plus a `showTab('X')` hook in JS. |
| Add a new WebSocket message | Firmware: extend `gamepad_build_state_json()` in `web_config.cpp`. Page side: handle `msg.type === '...'` in the WS onmessage handler in the mockup. |
| Change OTA upload behavior | `components/web_config/src/web_config.cpp` registers `/api/ota` (POST, multipart). The mockup's Settings tab has the matching `<form>`. |

## Build & flash

```bash
# 1. Build
pio run -e esp32-c3-devkitc-02
#  - First run: 5–15 min (downloads ESP-IDF + toolchain)
#  - Subsequent: ~15 s

# 2. Flash
pio run -e esp32-c3-devkitc-02 -t upload --upload-port COM6
#  - Output ends with "Hash of data verified" on success

# 3. Serial monitor (KEY: --rts 0 --dtr 0 to avoid spurious reboots
#    from the monitor's reset-line toggling)
pio device monitor -p COM6 -b 115200 --rts 0 --dtr 0 --no-reconnect

# 4. Regenerate HTML embed if you edited docs/config-ui-mockup.html:
python tools/gen_web_index.py
```

`platformio.ini` has an `extra_scripts = pre:tools/gen_web_index.py` line
so `pio run` regenerates the embedded HTML automatically.

## Tests

```bash
pip install pytest     # only dependency
pytest tests/ -q       # 256 tests, ~1 s
```

Tests are **static**: they parse C/H source on disk and assert contracts.
They will not catch runtime bugs. They ARE the cheap way to catch
"moved a function, forgot a forward declaration", "forgot to register
the route", "the namespace string drifted", etc. They can never replace
the bench test.

To run a specific module:

```bash
pytest tests/integration/test_output_config.py    # chunk 1+2+3+4+5 wiring
pytest tests/regression/test_structure.py        # v1.3 byte-identical guards
pytest tests/integration/test_pre_flash.py       # pre-flash stop sign
```

When you change a contract, update the test in the same patch — there is
no separate test suite owner.

## Constraints / non-obvious facts

1. **ESP32-C3 is BLE-only.** No classic BT. No WiFi-Direct. Implications:
   - Xbox 360 / PS4 DualShock classic BT: physically impossible.
   - Xbox One / PS5 DualSense / Switch Pro: proprietary BLE GATT, NOT supported yet.
   - Supported: standard HID gamepad (8BitDo, ipega, Gamesir, most "BT Controller").

2. **Framework = Arduino, not ESP-IDF.** This is deliberate. The
   Components-as-Arduino pattern works without manual `libbt.a` linking
   (raw NimBLE under PlatformIO once bricked an ESP32-C3 with ABI
   mismatch). Do not switch back to `framework = espidf` without first
   confirming the NimBLE-Arduino dep still resolves.

3. **`Arduino.h` is included in C files.** `main.c` is straight C but
   calls Arduino `setup()` from `app_main()`. If you add a `.c` file that
   wants C++ features (default member initializers, templates, etc.),
   rename to `.cpp` instead — or you'll burn a week on a single missing
   brace.

4. **`Constants.h` is C-compatible.** Any `ControllerState`-style struct
   shared between `myrobot/` and `ble_gamepad/` cannot use C++-only
   features (default initializers, namespaces, virtual methods).

5. **No ArduinoJson.** `output_config` hand-rolls a tiny JSON writer
   (~150 LOC) to save ~50 KB of flash. Don't add ArduinoJson to `lib_deps`
   unless you're prepared to measure the cost first.

6. **The `web_index_gen.h` is generated.** It's committed so the firmware
   builds without the generator, but it's run through `pio run` automatically.
   If you edit it by hand, your changes will be overwritten on the next build.

7. **WiFi AP has a `*\<EFUSE\>*` SSID.** The full SSID is printed to
   serial at boot, e.g. `Started AP: Combat-Robot-049D`. Don't hardcode it.

8. **ESP32-C3 native USB CDC, not UART0.** Default serial output goes to
   the USB connector. There's no UART0 console unless you explicitly
   reassign pins.

9. **`partitions.csv` is sized for exactly 4 MB.** Don't add a `littlefs`
   or `spiffs` partition — there's no room until you drop one of the
   `0x180000` app slots.

## Architecture — 60-second tour

```
main.c → app_main()
        ↓
sketch.cpp → setup() {  // called by Arduino after app_main
    nvs_flash_init();
    esp_netif_init();
    esp_event_loop_create_default();
    ble_gamepad_init();
    ble_gamepad_start();
    taskManager.begin();          // myrobot/TaskManager (v1.3 port)
    web_config_init();            // starts WiFi AP+STA, captive DNS, server, WS
}

loop() {
    handle_pairing_button();
    web_config_loop();
    delay(2);
}
```

```
                   ┌──────────────────────────────────┐
                   │      components/web_config/      │
                   │  (AsyncWebServer + AsyncWebSocket│
                   │    + AsyncTCP + AsyncEventSource │
                   │    + DNSServer on port 53)      │
                   └──┬───────────────────────────────┘
                      │  /, /api/*, /ws
                      ▼
       ┌───── browser on phone ─────┐
       │ 4 tabs (Controller/Outputs/  │
       │  Settings/About), WebSocket │
       │ subscribes to /ws            │
       └─────────────────────────────┘

  ┌────────────────────┐    ┌────────────────────────┐
  │ ble_gamepad.cpp    │    │ output_config.c        │
  │ (NimBLE host)      │    │ (NVS namespace         │
  │ - scan            │    │  output_cfg, blob      │
  │ - whitelist MAC   │    │  cfg_v1, JSON patch    │
  │ - HID parse →     │    │  parser)               │
  │   ControllerState │    │                        │
  └────────────────────┘    └────────────────────────┘
            │                          ▲
            │   ble_gamepad_get_       │
            │   state() used by        │
            │   gamepad_build_state_json
            │   in web_config.cpp       │
            └──────────────────────────┘

  ┌─────────────────────────────────────┐
  │ myrobot/    (v1.3 port: Drive, Drum,│
  │              TaskManager, etc.)     │
  │             ControllerState input   │
  │             → motor PWM via LEDC    │
  │             channels 0..3           │
  └─────────────────────────────────────┘
```

## Pitfalls (ranked by damage potential)

1. **Forgetting `EXTRA_SCRIPTS = pre:tools/gen_web_index.py`** when copying to a new clone. Without it, `pio run` builds stale HTML. Symptom: edits to the mockup don't appear on the device.

2. **Forgetting to call `arduinoLoop()` or `delay(2)` in `loop()`.** Without it the NimBLE host watchdog fires and you get stuck boot-loops. Don't refactor `loop()` away until you understand the watchdog dependency.

3. **Editing `web_index_gen.h` directly.** It gets regenerated; do it in the mockup.

4. **Picking `framework = espidf`.** Will surface `libbt.a` linker ABI issues against the bundled NimBLE. Don't.

5. **Adding a C++-only feature in `Constants.h`.** Breaks the `.c` files. Use `components/board_config/include/board_config.h` instead (already includes `inline constexpr` — but only `board_config.cpp` and `board_detect.cpp` include it).

6. **Forgetting `--rts 0 --dtr 0` when calling `pio device monitor`.**
   The monitor toggles RTS/DTR which resets the C3. You'll see the boot
   ROM banner twice and think it reset-loops. It didn't.

7. **BLE timeout (`CONFIG_BT_NIMBLE_MSYS_1_BLOCK_COUNT` etc.)** defaults
   in `sdkconfig.defaults` are tuned for a single connected controller.
   Bumping them costs ~5 KB flash each.

## Standard contribution workflow (recommended, not required)

1. Edit C code → `pio run` (rebuilds in ~15 s incremental).
2. Edit `docs/config-ui-mockup.html` → `pio run` (regenerates PROGMEM embed via pre-script).
3. Edit `tools/gen_web_index.py` or `partitions.csv` → `pio run` (re-applies config).
4. Run `pytest tests/ -q`. Update `tests/integration/test_output_config.py` if you changed contracts.
5. `pio run -t upload --upload-port COM6`.
6. `python tools/pc_ble_bench.py scan --bench-only` to confirm the board is alive and advertising.
7. `git add -A && git commit -m "..."` then `git push`.

## BLE bench tool

The board exposes a writable GATT characteristic so a PC can drive a
"synthetic gamepad" without needing a real controller:

```bash
python tools/pc_ble_bench.py scan --bench-only    # find CombatRobot-v2
python tools/pc_ble_bench.py write <MAC> --standard-frame --response
# writes the neutral frame: 7f 7f 7f 7f 00 00 00 00 08
# (LX, LY, RX, RY, buttons LE, buttons HI, LT, RT, hat)
```

This is the only way to exercise the BLE pipeline in CI or on a
workstation without an 8BitDo.

## Repository conventions

- **One chunk per commit.** Each commit message in this repo describes a
  single deliverable (e.g. "chunk 2: HTML embedded via gen_web_index.py").
- **`pio run` first, then `pytest`.** These are independent — both must
  pass before pushing.
- **`platformio.ini` extras script** + **`partitions.csv`** are the
  project-level authority for hardware config. If you change hardware,
  change them last.
- **Tests assert on the C source text, not the binary.** This lets us
  catch "moved a function but forgot to update the header" on a
  workstation without a compiler.

## Where to look for what

| If you want to understand… | Read… |
|---|---|
| Why a board pin is mapped where it is | `components/board_config/include/board_config.h` (extensive comments per `BOARD_REV`) |
| Why the BLE stack is NimBLE-Arduino and not Bluepad32 | `docs/DECISIONS.md` |
| Why the UI is a single static HTML file | `tools/gen_web_index.py` (it's 20 lines) |
| How the WebSocket integrates with the BLE pipeline | `components/web_config/src/web_config.cpp` `gamepad_build_state_json()` + `gamepad_ws_tick()` |
| What the device does on boot | `main/sketch.cpp::setup()` — followed by `components/web_config/src/web_config.cpp::web_config_init()` |
