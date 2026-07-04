# Changelog

## 2fc6cc4 — 2026-07-02 — BLE+WiFi+web UI overhaul

Five shipped chunks in one commit because they form a single coherent
feature ("remote-configurable combat robot controller").

### Chunk 1 — `output_config` component
- `components/output_config/{include,src,library.json,CMakeLists.txt}`: 5 logical outputs (M1, M2, Weapon, S1, S2), 24 controller input sources (LX, LY, RX, RY, LT, RT, A..DPAD_RIGHT), per-output direction toggle + servo uni/bi + deadzone + primary/secondary source mapping. Persisted in NVS namespace `output_cfg`, blob key `cfg_v1`.
- Hand-rolled JSON writer/parser (~150 LOC each) so we don't pull ArduinoJson (~50 KB flash cost).
- v1.3 default mapping preserved: M1/M2 ← LY, Weapon ← RT, S1/S2 unassigned.
- `tests/integration/test_output_config.py`: 28 tests covering public API, schema, NVS keys, defaults, patch parser validation.

### Chunk 2 — embedded mobile web UI
- `tools/gen_web_index.py`: pre-build script that wraps `docs/config-ui-mockup.html` as a `PROGMEM` raw-literal C header.
- `docs/config-ui-mockup.html`: mobile-first dark-theme UI. Sticky header, live stick/trigger visualizations, per-output cards.
- `platformio.ini` `extra_scripts = pre:tools/gen_web_index.py` ensures the embed regenerates on every build.

### Chunk 3 — WebSocket live gamepad feed
- `AsyncWebSocket` mounted at `/ws`.
- `gamepad_ws_tick()` in `web_config.cpp::web_config_loop()` sends the latest `ControllerState` at 30 Hz whenever a WS client is connected AND a controller is paired (gated by `ble_gamepad_set_connection_callback`).
- Mockup auto-connects to `/ws` after page load.

### Chunk 4 — captive portal DNS
- `DNSServer` on port 53 in `start_ap_mode()`. Responds to every query with the AP IP.
- `onNotFound` redirects every non-`/api/*` path to `/`.
- Result: phone joins the AP, opens any URL, lands on the dashboard — no need to type `192.168.4.1`.

### Chunk 5 — tabbed UI restoration
- Replaced single-page dashboard with 4 tabs: **Controller** (pairing + live gamepad) / **Outputs** (M1/M2/Weapon/S1/S2 dropdowns, direction toggles, deadzone, servo bi/uni) / **Settings** (WiFi, board-rev override, OTA firmware upload) / **About** (status, board info).
- All REST endpoints (pair/start, pair/cancel, pair/clear, board/rev, board/reset, OTA) wired to the matching UI affordances.

### Plumbing / hygiene
- PlatformIO env pinned at `espressif32@6.5.0` (Arduino 2.0.14, ESP-IDF 5.1.x).
- `partitions.csv` refit for 4MB flash: 2 × `0x180000` app slots ending at `0x310000`, SPIFFS at `0x310000`–`0x400000`.
- Myrobot `LEDC` calls migrated to explicit channels (LEDC v1→v2 API break).
- Build evidence: RAM 14.6%, Flash 69.1%. `firmware.bin` = 1,153,424 bytes (with DNSServer).
- Board flashed to COM6, hash-verified, BLE-bench-verified alive (MAC `28:37:2F:CB:9D:06`, advertises `CombatRobot-v2`).
- Full test suite: **256 passed, 4 skipped**.

## Upstream history (before this commit)

- `847fbff` Build config updates for attempted flash: pin platform, drop bogus NimBLE dep, gitignore build artifacts
- `d4478c1` Simplify board_detect to NVS-only (Option 1)
- `da20ff3` Add runtime board detection (3-layer: NVS > hardware > compile-time)
- `d4c48a2` Add v3 BLDC breakout (CN5) support: 4 motor drivers, 7-pin header, 50Hz servo PWM
- `5ab619f` Add board_config.h abstraction layer (v2 + v3 support) and BOARD_HARDWARE.md

## Known issues (deferred, not blocking current build)

These were surfaced by a 2026-07-04 three-agent static review
(bug-hunt / security / memory-concurrency) but not fixed in this
session — each needs either its own design pass or follow-up commits.

### Security — `security` profile only

- **Hard-coded AP password `"fightbot"`** (`web_config.cpp:49,56`).
  Anyone within WiFi range can associate with `CombatRobot-<EFUSE>`.
  No REST endpoint under `/api/` requires any authentication:
  `POST /api/config` (motor direction, weapon binding),
  `POST /api/board/rev` (NVS GPIO remap), and `POST /api/ota` (raw
  firmware upload, no signature, no size cap) are all open.
  Fix requires a shared-secret/token model and a path to migrate
  existing deployments.
- **BLE Just-Works pairing with `mitm=false`, `sc=true`**
  (`ble_gamepad.cpp:601–603`). Active-MITM attacker can proxy first
  pairing, the cloned MAC then gets bonded + auto-whitelisted on
  every subsequent boot. Hard-coded passkey `000000` (`onPassKeyRequest`
  at line 347). Fix requires user-facing pairing flow change.

### Bug-hunt — minor / latent

- **`BoardConfig` class referenced in `TaskManager.cpp:19` but never
  defined** (`board_config/` only defines `BoardInfo`). Currently
  compiles because `Drum` uses hardcoded `ESC_1_PIN` directly and
  bypasses `BoardConfig::getPins`. The dead class should be either
  implemented or removed.
- **No `extern "C"` guards** in `ble_gamepad.h`, `board_config.h`,
  `board_detect.h`, `web_config.h`, `myrobot/Constants.h`. Compiles
  today because Arduino's C++ entry point absorbs the linkage but
  is fragile if `main.c` ever calls these directly.
- **`rgbLED.h` uses `#pragma once`** while every other header in the
  project uses `#ifndef` guards. Style inconsistency, no functional
  impact.

### Memory & concurrency — design notes

- **Unprotected `s_state.controller_state`** between NimBLE task and
  Arduino `loop()`. Single-core RISC-V with FreeRTOS preemption means
  `ble_gamepad_get_state()` (struct-copy return at `ble_gamepad.cpp:661`)
  can yield a torn frame during the field-by-field write at
  `ble_gamepad.cpp:273–280`. Worst-case is a single-frame inconsistent
  stick/trigger value. Fix is `portENTER_CRITICAL` around the copy.
- **`DNSServer.start(53, ...)` called from `start_ap_mode()` on every
  AP re-entry.** Currently safe because the call is preceded by an
  explicit `dnsServer.stop()` and `setErrorReplyCode()` is idempotent,
  but `start_ap_mode()` runs every time STA drops — needs a one-shot
  guard if observed in the wild.
- **`TaskManager::managerTask` runs on 4096 bytes of stack** under
  Arduino default (`TaskManager.cpp:73–81`). Tight given the
  `combined_direction` → `DriveMotor` chain plus `adjustLedForBattery`
  rainbow-buffer allocations. Bump to 5120–6144 if WDT fires.
- **AsyncWebServer `String` body accumulation leaks on aborted
  requests** (`web_config.cpp:350–358`). `_tempObject` is only freed
  on the success path; abort + OTA timeout leaves a multi-MB
  allocation parked until client disconnect. Use a fixed-size buffer
  for small JSON PATCHes and an explicit cleanup hook for multipart.

(Older history not preserved — fresh repo, parent remote had no shared
lineage once the public repo was created.)
