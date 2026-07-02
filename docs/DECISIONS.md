# Combat Robot v2 — Architecture Decisions

**Project:** Combat robot firmware rewrite, based on `schwimmflugel/esp-idf-arduino-bluepad32-template` (`combat_robot` branch).
**Started:** 2026-06-29
**Primary target board:** ESP32-C3 DevKitC-02 (4MB flash, BLE-only, no classic Bluetooth)

This document captures **what we decided, why, and what we learned along the way**. It's the source of truth for the project's architecture. If you (or future-you) wonder "why didn't we just use Bluepad32?" — the answer is here.

---

## 1. Why are we rewriting this?

### The old stack (v1.3 / `combat_robot` branch)

```
+-------------------+    +-----------------+    +----------------+
| Bluepad32 (C++)   |--->| BTstack (BR/EDR |    | Arduino-esp32  |
| ~5000 LOC parser  |    | +BLE dualmode)  |--->| runtime        |
| Xbox/PS/Switch/   |    |                 |    | ~300KB flash   |
| 8BitDo/keyboard/  |    |                 |    |                |
| mouse etc.        |    |                 |    |                |
+-------------------+    +-----------------+    +----------------+
        |                                                |
        v                                                v
+-------------------+                        +-------------------+
| myrobot component |                        | Adafruit_NeoPixel |
| TaskManager +     |<-----------------------| (RMT driver)      |
| Drive/Drum/Batt   |                        | ~3800 LOC         |
+-------------------+                        +-------------------+
```

**Total flash:** ~1.5–1.8MB. **Compile time:** several minutes. **Repo size:** lots of code we don't use.

### What we actually used from Bluepad32

A *tiny* slice. The robot loop in v1.3 only reads five values from the controller:

```cpp
controllerState.leftStickY    = myControllers[0]->axisY();     // -512..511
controllerState.rightStickY   = myControllers[0]->axisRY();    // -512..511
controllerState.rightTrigger  = myControllers[0]->throttle(); // 0..1023
controllerState.leftTrigger   = myControllers[0]->brake();    // 0..1023
controllerState.buttons       = myControllers[0]->buttons();  // 16-bit mask
```

Five integers. No gyro. No accelerometer. No dpad. No haptic feedback. No lightbar control. We were paying for **20+ controller protocols** (Xbox One, Xbox 360, PS4, PS5, Switch Pro, Wii, 8BitDo variants, iCade, keyboard, mouse, balance board, etc.) when we only ever use one BLE gamepad.

### Specific v1.3 pain points (your words)

1. **"Library is very heavy for my simple custom robot libraries"** — flash and compile time.
2. **"I need to package the full Arduino stack just for it to compile"** — Arduino is required because BP32 is C++ and pulls `Arduino.h` everywhere.
3. **"Want more simplicity"** — repo is large, hard to reason about.
4. **"If a controller loses power mid-fight, you can't reconnect without resetting the ESP32"** — your existing code locks after first connect, but unlocking is brittle.

### Plus an unstated pain point you discovered during the v1.3 build

The `WebInterface.cpp` and `OtaUpdater.cpp` files exist but are **broken**:
- `handleUpdate()` is empty.
- `handleStatus()` has a brace but no body.
- `handleRoot()` uses `)rawliteral` (typo) instead of `)rawliteral";`.
- Uses `WiFi.mode(WIFI_AP)` only — no STA, no captive portal.
- Open AP (no password), with `/upload` endpoint — anyone in range can flash malicious firmware.

We need a real web config UI anyway, so this gets rewritten from scratch.

---

## 2. The new stack (v2)

```
+----------------------+      +----------------------+      +----------------------+
| NimBLE host          |      | AsyncWebServer       |      | Arduino-esp32        |
| (BLE-only, ~150KB)   |      | (async, doesn't      |      | (kept for hobbyist   |
| Standard HID gamepad |      | block main loop)     |      | compatibility)       |
| parser               |      |                      |      |                      |
| ~300 LOC             |      |                      |      |                      |
+----------------------+      +----------------------+      +----------------------+
        |                             |                              |
        v                             v                              v
+----------------------+      +----------------------+      +----------------------+
| ble_gamepad          |      | web_config           |      | myrobot (ported)     |
| component            |      | component            |      | TaskManager, Drive,  |
| - HID descriptor     |      | - HTML UI (LittleFS  |      | Drum, PowerFunc,     |
|   parser             |      |   or PROGMEM)        |      | Buttons, LED, rgbLED |
| - Pairing mode       |      | - NVS-backed config  |      |                      |
| - MAC whitelist NVS  |      | - Pairing API        |      |                      |
| - Connection lock    |      | - OTA endpoint       |      |                      |
+----------------------+      +----------------------+      +----------------------+
```

**Total flash target:** <1MB. **Compile time target:** <60 seconds incremental. **Repo size:** ~2000 LOC robot + ~1500 LOC new infrastructure.

---

## 3. Key decisions

### D1. Controller: 8BitDo (BLE mode) ✅

**Decision:** Ship with 8BitDo Ultimate / Pro 2 in BLE mode as the supported controller.

**Why:**
- Standard Bluetooth HID gamepad protocol (no proprietary parser).
- Works on ESP32-C3 (BLE-only).
- Easy to source, secure supply chain (8BitDo is established, sold through major distributors).
- Multiple modern SKUs in production.
- ~$40–$60, widely available.

**Rejected alternatives:**
- **Xbox One:** Proprietary Microsoft GATT protocol, ~500+ LOC parser, no open spec. Only viable via Bluepad32.
- **Xbox 360:** Classic BT only, doesn't work on C3 (no BR/EDR radio).
- **PS5 DualSense:** Vendor reports, ~300 LOC, pairing is finicky (hold Create+PS for 5s).
- **Keyboard/mouse:** Out of scope per user.

### D2. BLE stack: NimBLE (Apache 2.0, in ESP-IDF) ✅

**Decision:** Use NimBLE host stack, not Bluedroid.

**Why:**
- ~150KB smaller flash than Bluedroid.
- Better suited to ESP32-C3 (smaller RAM footprint).
- Apache 2.0 licensed (compatible with our project).
- Already in ESP-IDF component registry, no separate vendoring.

**Rejected:** Bluedroid (Android-derived, ~200KB more flash, more RAM). Bluepad32 (which uses BTstack) — the whole point is to drop it.

### D3. Keep Arduino framework ✅

**Decision:** Stay on Arduino-esp32 framework via PlatformIO.

**Why:**
- User explicitly wanted hobbyist accessibility.
- `myrobot` component heavily uses Arduino classes (`Adafruit_NeoPixel`, `String`, `ledcAttach`, `ledcWrite`).
- Selective Arduino compilation (`CONFIG_ARDUINO_SELECTIVE_*`) already trims unused parts.
- Dropping Arduino means rewriting ~5800 LOC of robot code, which is out of scope.

**Trade-off:** Still pulls Arduino runtime (~200KB), but we get to keep all the battle-tested robot code.

### D4. Toolchain: PlatformIO ✅

**Decision:** Continue using PlatformIO (PIO).

**Why:**
- `platformio.ini` already has all 5 board targets configured (`esp32dev`, `esp32-s3-devkitc-1`, `esp32-c3-devkitc-02`, `esp32-c6-devkitc-1`, `esp32-h2-devkitm-1`).
- User preference.
- PIO is fine for ESP-IDF + Arduino hybrid projects.

### D5. Web server: ESPAsyncWebServer ✅

**Decision:** Use ESPAsyncWebServer (mehlma/ESPAsyncWebServer) on top of ESP-IDF's async TCP stack.

**Why:**
- Arduino `WebServer` is **synchronous** — `handleClient()` blocks until request done. This would block the 10Hz motor control loop in `loop()` and cause robot stuttering.
- ESPAsyncWebServer runs handlers on a separate task; main loop never blocks.
- Handles websockets, chunked responses, file uploads naturally.
- Already widely used in ESP32 hobbyist projects.

**Rejected:** `esp_http_server` (ESP-IDF native, also async) — works fine but more boilerplate, less hobbyist-friendly.

### D6. WiFi: AP+STA with captive portal fallback ✅

**Decision:** Try saved STA credentials from NVS. If fail, start AP mode with captive portal. Once configured, reboot into STA.

**Why:**
- First-time setup needs *some* way to configure WiFi.
- Captive portal is the standard hobbyist pattern.
- After config, runs as STA connected to home WiFi (or competition WiFi).

**Trade-off:** Slightly more complex WiFi state machine. Captive portal adds ~50KB flash for the redirect logic.

### D7. Pairing model: button-triggered with NVS whitelist ✅

**Decision:**
- Physical button (existing `MODE_BUTTON_PIN` GPIO5) cycles modes: NORMAL → PAIRING → UNPAIR.
- Long-press (3s) in PAIRING mode = erase whitelist and enter "accept any" mode for 60s.
- HTML UI has equivalent buttons.
- NVS stores up to 4 whitelisted controller MACs.
- After first controller connects, lock to that MAC (your existing behavior).

**Why:**
- Matches your existing v1.3 pattern (lock after first connect).
- Solves "controller dies mid-fight, can't reconnect without reset" — just press button to re-enter pairing.
- Whitelist prevents random phones from taking control mid-fight.

### D8. Web config scope (phased) ✅

**Decision:** Web UI is built in phases. Phase 1 = pairing + status + OTA. Phase 2+ = motor/pin/input/LED config (requires refactoring `myrobot` subsystems to be config-driven).

**Phase 1 endpoints (this PR):**
- `GET /` — status dashboard (battery, controller state, paired MAC).
- `POST /api/pair/start` — enter pairing mode.
- `POST /api/pair/cancel` — exit pairing mode.
- `POST /api/pair/clear` — clear whitelist.
- `GET /api/config/pair` — list paired MACs.
- `POST /api/ota` — upload firmware.

**Phase 2+ (later):**
- `GET/POST /api/config/pins` — pin assignments per motor.
- `GET/POST /api/config/pwm` — PWM frequency/resolution per output.
- `GET/POST /api/config/input` — gamepad channel → motor input mapping.
- `GET/POST /api/config/led` — LED effect, color, brightness.

**Why phased:** Each phase is testable. Phase 1 doesn't require refactoring `myrobot`. Phase 2+ breaks the compile-time-fixed pin/freq/resolution constants in `Constants.h` and is a real refactor.

### D9. Security: AP password, OTA auth, input validation ✅

**Decision:**
- AP password is configurable (random default, printed to serial on first boot).
- OTA requires same AP password (cookie-based auth).
- All POST endpoints validate input strictly.

**Why:** v1.3 had an open AP with an OTA endpoint — anyone in range could flash malicious firmware. We're not making that mistake twice.

---

## 4. Lessons learned (so far)

### L1. The existing web code is broken — replace, don't extend

When porting `WebInterface.cpp` from v1.3, I found:
- `handleUpdate()` is empty.
- `handleStatus()` has unclosed brace.
- `handleRoot()` uses `)rawliteral` (typo) instead of `)rawliteral";`.
- WiFi is open AP only, no STA mode.
- OTA endpoint uses `Serial` which isn't available.

**Lesson:** When v1 code looks half-done, don't try to fix it in-place. Rewrite from scratch with a clear design.

### L2. Arduino `WebServer` is synchronous — don't use for real-time

`WebServer::handleClient()` blocks until request done. For a robot with a 10Hz control loop, a 200ms page load = 2 missed motor updates = stuttering.

**Lesson:** Always use an async web server on ESP32 when you have a real-time control loop. ESPAsyncWebServer is the standard hobbyist choice.

### L3. ESP32-C3 has no classic Bluetooth radio

Xbox 360, PS4 (DualShock 4), and other classic-BT controllers do **not work** on C3. Only BLE-mode controllers work (Xbox One, Xbox Series, PS5 DualSense in BLE mode, 8BitDo, Switch Pro, etc.).

**Lesson:** When picking a controller for a BLE-only chip, verify it's BLE-mode, not BR/EDR-only.

### L4. The big flash consumer isn't Bluepad32 — it's Adafruit_NeoPixel

`Adafruit_NeoPixel.cpp` is 3835 lines and pulls in RMT driver glue. That's likely ~300–400KB of flash on its own, more than Bluepad32. If flash size becomes a problem post-rewrite, **swap NeoPixel for the ESP-IDF `led_strip` component**, not strip Bluepad32.

**Lesson:** Profile before optimizing. Don't assume the suspected heavy thing is actually heavy.

### L5. `delay()` + `vTaskDelay()` in the main loop caps control rate

`vTaskDelay(pdMS_TO_TICKS(100))` in `loop()` caps the control rate at 10Hz. For a combat robot, 50Hz feels noticeably more responsive. This is a tuning concern, not a BLE rewrite concern, but worth flagging.

**Lesson:** The loop's worst-case latency is its control rate. Don't put unconditional delays in there.

### L6. Pairing mode "lock after first connect" needs an unlock path

Your v1.3 code: `enableNewBluetoothConnections(false)` after first connect, `enableNewBluetoothConnections(true)` when `myControllers[0]==nullptr`. The bug: `myControllers[0]==nullptr` is true on boot, so the unlock fires immediately and never re-locks properly.

**Lesson:** Pairing state needs explicit mode tracking, not implicit "controller slot empty" logic. We're using a `PairingState` enum: `RUNNING | PAIRING | PAIRED`.

### L7. PlatformIO + ESP-IDF requires `framework = espidf` even when using Arduino

Your `platformio.ini` says `framework = espidf` but `main.c` uses `Arduino.h`. This works because PIO pulls `arduino` as a CMake component (`requires arduino`). Counter-intuitive but correct.

**Lesson:** When porting PIO projects, keep the framework setting even if it looks wrong. The Arduino components come from `requires`/`lib_deps`, not from `framework = arduino`.

---

## 5. Open questions / TODO

- [ ] Which 8BitDo model exactly? (Ultimate Wireless vs Pro 2 vs SN30 Pro) — affects button mapping.
- [ ] Does the user actually want the HTML UI to control *live* motor config (dangerous in a fight) or just persist config for next boot (safer)?
- [ ] Should the Web UI be on the local network only, or also exposable via the captive portal (when in AP mode)?
- [ ] BLE pairing security level: Just Works (no PIN) or passkey entry (6-digit PIN)?
- [ ] OTA: signed firmware (more secure) or unsigned (simpler)?

---

## 6. Files of note

- `main/` — `app_main` (was `main.c`), Arduino `setup()`/`loop()` (was `sketch.cpp`).
- `components/myrobot/` — ported from v1.3, no functional changes yet.
- `components/board_config/` — per-`BOARD_REV` pin map + `BoardInfo` struct.
- `components/output_config/` — NVS-backed per-output config (direction toggle, source mapping, deadzone).
- `components/ble_gamepad/` — **NEW**, NimBLE HID parser + pairing mode + bench GATT server for PC bench tests.
- `components/web_config/` — **NEW**, async web server + HTML UI + WebSocket live feed + captive-portal DNS.
- `docs/DECISIONS.md` — this file.
- `docs/AGENT.md` — ⭐ READ FIRST if you're picking up this codebase cold.
- `docs/CHANGELOG.md` — what shipped in each commit.
- `docs/BUILD.md` — build instructions (verified for Windows / Git Bash / PlatformIO 6.1.19).
- `docs/TESTING.md` — how to test on hardware + what each test demonstrates.

---

## 7. Outcomes (as of commit 2fc6cc4)

Every L1–L7 lesson in section 4 was applied:

- § 4L1 → `output_config` component is pure C, hand-rolls its own JSON writer/parser (~150 LOC each, no ArduinoJson).
- § 4L3 → NimBLE-Arduino at v1.4.3, with the standard 0x1812 HID parser accepting the 8BitDo Ultimate 2 in BLE mode.
- § 4L4 → `lib_extra_dirs = components` plus each `library.json` so PlatformIO picks up the custom components.
- § 4L5 → 4MB partitions (factory + ota_0 + spiffs), each ≤ `0x180000`.
- § 4L7 → `framework = arduino` (not espidf) — final, no longer mixed-mode.

Additional lessons learned (out of scope of the original L1–L7):

- **ESPAsyncWebServer 3.6.0 body handler signature is `(req, uint8_t*, size_t, size_t, size_t)`** — not the older `(req, body)` String variant. Buffer the body manually via `req->_tempObject` if you need String semantics.
- **AsyncWebSocket on the same port (80) needs `server->addHandler(ws)`** before routes are registered, or the routes will shadow the WS upgrade.
- **Captive-portal DNS** must run on the AP IP and use `setErrorReplyCode(NoError)` so probe hosts that don't trust CNAMEs still get the right answer. Combined with `onNotFound` redirecting to `/`, this is enough — no need for a dedicated landing page.
- **Phone `<input type="file">` triggers "Open with..."** dialog on iOS/Android. The OTA form is a real `<form enctype="multipart/form-data">` posting to `/api/ota`, no JS handlers.