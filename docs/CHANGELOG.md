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

(Older history not preserved — fresh repo, parent remote had no shared
lineage once the public repo was created.)
