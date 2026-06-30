# Combat Robot v2 — Test Suite

Host-side tests for combat-robot-v2 firmware. Run before every flash, and on
every commit when wired to CI.

## Quick start

```bash
# Install test deps (one-time)
pip install -r tests/requirements.txt

# Run everything
pytest tests/

# Run just the unit tests
pytest tests/unit/

# Run with verbose output
pytest tests/ -v

# Run a specific test
pytest tests/unit/test_hid_parser.py::test_axis_scaling_center -v
```

## What this catches

| Test file | Catches | Doesn't catch |
|---|---|---|
| `unit/test_hid_parser.py` | HID report parsing logic (axis scaling, button bit positions, hat switch encoding) — the part that varies by controller | Real hardware behavior; NimBLE GATT issues |
| `unit/test_nvs_whitelist.py` | Whitelist add/remove/overflow; MAC equality | Real NVS flash storage behavior |
| `unit/test_status_api.py` | JSON shape the HTML expects matches what the C++ produces | HTML rendering bugs |
| `regression/test_ported_files.py` | Anything you change in `myrobot/` that you didn't mean to | Anything outside the ported files |
| `regression/test_api_consistency.py` | Every public BLE function declared in `.h` is defined in `.cpp` | Logic bugs inside the function bodies |
| `regression/test_pin_defines.py` | Pin assignments in `Constants.h` match what the schematic says (once we wire that in) | Wiring mistakes outside the schematic |
| `integration/test_pre_flash.py` | All of the above, plus known-bad checks (pinout mismatch, etc.) | Hardware behavior |

## What this doesn't catch (yet)

- **NimBLE GATT discovery** — requires real BLE peripheral and ESP32
- **PWM output on real motor drivers** — requires real hardware
- **HTML rendering** — would need a headless browser (Playwright)
- **OTA upload** — needs HTTP server on real device
- **Captive portal DNS** — needs AP mode on real device

These are deferred to **on-target tests** using ESP-IDF's Unity framework,
which we'll add when there's hardware to run them on. The structure is ready
(`tests/integration/` is reserved for this).

## Layout

```
tests/
├── README.md                    # This file
├── requirements.txt             # pytest + deps
├── pytest.ini                   # pytest config
├── conftest.py                  # Shared fixtures
├── unit/                        # Pure logic tests, fast
│   ├── test_hid_parser.py
│   ├── test_nvs_whitelist.py
│   └── test_status_api.py
├── regression/                  # Code-shape tests, slower
│   ├── test_ported_files.py
│   ├── test_api_consistency.py
│   └── test_pin_defines.py
├── integration/                 # Reserved for on-target Unity tests
│   └── .gitkeep
└── fixtures/                    # Sample data, mock gamepad reports
    └── mock_hid_reports.py
```

## Adding a new test

1. Pick the right layer: logic → `unit/`, code shape → `regression/`, on-target → `integration/`.
2. File name: `test_<thing>.py`.
3. Run `pytest tests/ -v` to confirm it picks up.
4. Add a row to the "What this catches" table above.

## Honest scope of these tests

Most `unit/` tests are **specification capture, not code coverage**. They
document what the C++ code SHOULD do, and exercise the same algorithm in
Python. When the C++ implementation drifts from the spec, the test fails
loudly. This is *not* a substitute for running the C++ code, but it's
infinitely better than nothing — and it documents the intent so a future
contributor knows what each piece is supposed to do.

The `regression/` tests DO run against the actual C++ source — they parse
the files and check shape, not behavior. So those are real.

See `docs/TESTING.md` (in the project root) for the manual hardware test plan
that complements these automated tests.