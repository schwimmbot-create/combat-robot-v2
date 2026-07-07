# Hardware bench E2E test

Use this after large firmware changes to verify the real bench setup still works end-to-end:

- original ESP32-C3 robot controller connected over USB
- LilyGo T-Dongle-S3 mock 8BitDo controller connected over USB
- both devices already flashed with the current robot/mock firmware
- the host connected to the robot AP (`Combat-Robot-049D`, password `fightbot`) if you want WiFi/API coverage

Run from the robot controller repo:

```bash
cd ~/projects/combat-robot-controller-v2
.venv/bin/python tools/bench_e2e.py
```

The script auto-detects the current bench devices by USB serial/MAC:

- robot controller: `28:37:2F:CB:9D:04`
- S3 mock controller: `30:ED:A0:D7:75:F4`

Override ports, serials, or API URL if needed:

```bash
.venv/bin/python tools/bench_e2e.py \
  --robot-port /dev/ttyACM1 \
  --mock-port /dev/ttyACM0

.venv/bin/python tools/bench_e2e.py \
  --robot-serial 28:37:2F:CB:9D:04 \
  --mock-serial 30:ED:A0:D7:75:F4

.venv/bin/python tools/bench_e2e.py \
  --api-base http://192.168.4.1
```

Skip WiFi/API checks when the AP is not connected:

```bash
.venv/bin/python tools/bench_e2e.py --skip-api
```

To connect the Beelink's spare TP-Link adapter without stealing the default route:

```bash
nmcli con add type wifi ifname wlxaca7f1bd9068 \
  con-name robot-bench-combat-049d-user \
  ssid Combat-Robot-049D \
  connection.permissions user:openclaw

nmcli con modify robot-bench-combat-049d-user \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk fightbot \
  ipv4.method auto \
  ipv4.never-default yes \
  ipv4.route-metric 900 \
  ipv6.method disabled \
  connection.autoconnect no

nmcli con up robot-bench-combat-049d-user ifname wlxaca7f1bd9068
```

## What it checks

1. Finds both USB boards and refuses to run if it cannot distinguish them.
2. Confirms the robot serial CLI responds.
3. Confirms the S3 mock-gamepad serial CLI responds.
4. Ensures the robot board is connected to the mock HID peripheral, entering pairing mode over serial if needed.
5. Sends mock controller states over the S3 CLI and verifies the robot CLI reports matching parsed state:
   - centered neutral
   - `LY=0 -> -508`
   - `LY=255 -> 512`
   - `L2=255 -> 1020`, `R2=128 -> 512`
   - `BTN=A,B,START -> buttons=515`
   - `HAT=N -> dpad=1`
   - reset back to neutral
6. Exercises the robot WiFi API at `http://192.168.4.1`:
   - `GET /api/status`
   - `GET /api/bench/hid/status`
   - `POST /api/bench/hid?hex=<10-byte-8BitDo-report>`
7. Verifies API bench HID injection is visible through the robot serial CLI:
   - `A` button -> `buttons=1`
   - `LY=0`, `R2=64`, `L2=32` -> `ly=-508`, `rt=256`, `lt=128`
8. Verifies four-channel S1/S2 role support through `/api/config` plus API HID injection:
   - confirms obsolete top-level `Weapon` config patches are rejected; weapon-like behavior must be assigned to S1 or S2
   - configures `S1` as `purpose=digital_output`, `protocol=gpio`, `semantics=digital_output`
   - Button A direct mode: released -> logical off / physical LOW, pressed -> logical on / physical HIGH
   - active-low inversion: released -> physical HIGH, pressed -> physical LOW
   - RT `trigger_half` preset: below threshold stays off, half press turns on
   - RT custom threshold: below threshold off, above threshold on, hysteresis holds on, off threshold turns off
   - restores `S1` back to safe servo-style defaults before exiting
9. Leaves the bench in normal real-BLE state for manual follow-up.

A successful run ends with:

```text
BENCH_E2E PASS
```

## Notes

This is intentionally not part of normal `pytest` because it requires physical hardware and active serial ports. Run it manually after firmware changes that could affect BLE, pairing, HID parsing, control-state mapping, serial CLI behavior, or board boot/reset behavior.
