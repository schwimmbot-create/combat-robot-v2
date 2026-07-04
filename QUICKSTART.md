# Combat Robot v2 — local quickstart

> Read [`docs/AGENT.md`](docs/AGENT.md) first. This file is the *short*
> version for getting unblocked on this Linux box.

## What this repo is

ESP32-C3 BLE combat-robot controller: NimBLE host that pairs an 8BitDo
Ultimate 2 gamepad, runs the v1.3 `myrobot` drive/drum/task pipeline,
and exposes a mobile-friendly web UI (REST + WebSocket) for NVS-persisted
per-output config.

- **Upstream:** <https://github.com/schwimmbot-create/combat-robot-v2>
- **Author:** Kevin Brown (schwimmflugel.com)
- **Local clone:** `~/projects/combat-robot-controller-v2/`
- **HEAD at clone:** `9ad95fe` (master) — "test: add mock robot drive preview and simulator"

## Toolchain — what's installed on this box

| Tool | Version | Location | How installed |
|---|---|---|---|
| `python3` (system) | 3.12.3 | `/usr/bin/python3` | distro |
| `uv` | latest | `~/.local/bin/uv` | already on PATH |
| `gcc`, `make`, `cmake` | — | system | already present |
| `platformio` (Core) | 6.1.19 | `.venv/bin/pio` | `make setup` |
| `pytest` | 9.1.1 | `.venv/bin/pytest` | `make setup` |
| `bleak` | ≥ 0.22 | `.venv/bin/python -m bleak` | `make setup` |
| `esptool` | (bundled) | downloaded by PIO | implicit, on first `make build` |
| ESP-IDF + xtensa toolchain | — | `~/.platformio/packages/` | downloaded by PIO, on first `make build` (~5–15 min, ~1 GB) |

**Not installed and not needed for now:**

- `ninja-build` — PlatformIO's Arduino build path doesn't require it on
  this project. If you switch a component to `framework = espidf`, install
  it: `sudo apt-get install -y ninja-build`.
- `python3-venv` system pkg — `uv` provides its own venv bootstrap.

## Quickstart

```bash
cd ~/projects/combat-robot-controller-v2

# One-time setup (~10 s; ESP-IDF + toolchain come later on first build)
make setup

# Fast loop — static tests, no hardware needed
make test                 # 292 passed, 22 skipped (v1 reference absent), ~0.5 s

# BLE bench, no board attached
make bench-scan           # prints every BLE device; looks for "CombatRobot-v2"

# Firmware build (downloads ESP-IDF + toolchain on first run, ~5–15 min)
make build                # default env: esp32-c3-devkitc-02

# Build + flash + serial monitor (USB cable attached, /dev/ttyACM0 by default)
make flash PORT=/dev/ttyACM0
make monitor PORT=/dev/ttyACM0
```

### Build environments

| Env | Board | Notes |
|---|---|---|
| `esp32-c3-devkitc-02` | ESP32-C3 DevKitM-1 (RISC-V) | **primary target**, BLE-only |
| `esp32-c3-devkitc-02-dev` | same board | adds `-D BENCH_HID_PUBLIC=1` — anyone can pair, dev only |
| `esp32dev` | original ESP32 (Xtensa) | legacy sanity check |
| `esp32-s3-devkitc-1` | ESP32-S3 | sibling-radio bench test |
| `esp32-c6-devkitc-1` | ESP32-C6 | 802.15.4 sibling |
| `esp32-h2-devkitm-1` | ESP32-H2 | Thread/Zigbee sibling |

Switch with `make build ENV=esp32-s3-devkitc-1`, etc.

## BLE bench — driving the board from your laptop

```bash
# Find the board (advertises as "CombatRobot-v2")
make bench-scan

# Write a neutral synthetic HID frame (no real gamepad needed)
BENCH_MAC=AA:BB:CC:DD:EE:FF make bench-write
```

Full CLI: `python tools/pc_ble_bench.py {scan,notify,write} --help`

## Files in this repo that *I* added

| File | Why |
|---|---|
| `Makefile` | one-command wrapper around `pio`, `pytest`, `pc_ble_bench.py`. Honors `ENV=`, `PORT=`, `BAUD=`, `BENCH_MAC=`. |
| `QUICKSTART.md` | this file |
| `.venv/` | gitignored-by-convention; project-local Python 3.12 venv with platformio + pytest + bleak |

**Files I edited:**

| File | What changed | Why |
|---|---|---|
| `tools/gen_web_index.py` | resolves `PROJECT_ROOT` from `__file__` instead of hard-coded `C:\Users\kbrow\Documents\Codex\combat-robot-v2` | the build's pre-script failed on this Linux box; still works on your Windows laptop because it falls back to the literal path if the file is found there |

## Things you should do manually

1. **Decide whether to commit `gen_web_index.py` patch.** It's a clear
   improvement (cross-platform, no behavior change on your laptop), but
   I didn't touch git because I wasn't sure if you'd prefer to push it
   upstream as a PR or keep it local. `git diff tools/gen_web_index.py`
   shows the patch.

2. **Add `.venv/` to `.gitignore`** if you want this to stay clean.
   Currently the repo's `.gitignore` covers `.pio/`, `__pycache__/`,
   etc. but not `.venv/`. One-line addition:

   ```bash
   echo ".venv/" >> .gitignore
   ```

3. **(Optional) Install `ninja-build`** for faster ESP-IDF builds if you
   ever switch a component away from Arduino:

   ```bash
   sudo apt-get install -y ninja-build
   ```

   Not needed for the current Arduino framework path.

4. **USB device detection:** the box already has `/dev/ttyACM0` attached.
   Confirm it's actually the C3 (not a leftover from another project):

   ```bash
   ls -l /dev/ttyACM0
   dmesg | tail -20 | grep -i cdc      # ESP32-C3 native USB CDC shows up here
   ```

   If `ttyACM0` belongs to something else, your real C3 is likely
   `ttyACM1` or `ttyUSB0` — use `PORT=/dev/ttyACM1 make flash`.

## Pre-flight checklist (per docs/TESTING.md)

```bash
make test           # 292 tests, must be green
make build          # firmware compiles, ends with size summary
make bench-scan     # board is advertising as CombatRobot-v2
make flash          # "Hash of data verified" at the end
make monitor        # boot banner prints, no double-reset
```