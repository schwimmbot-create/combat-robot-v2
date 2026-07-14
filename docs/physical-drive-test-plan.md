# Physical Drive Test Environment

This plan complements the firmware serial/API bench (`tools/bench_e2e.py`). The bench proves controller decoding, config parsing, drive math, motor intent telemetry, servo/ESC pulse intent, power behavior, and failsafe logic. Physical drive testing proves the remaining layer: wiring, motor orientation, wheel direction, steering linkage direction, traction, and real robot motion.

## Goals

1. Confirm that firmware intent matches physical movement for:
   - 2-wheel differential/skid bots.
   - 4-wheel skid bots with left/right motor groups.
   - servo-steer bots.
2. Catch physical integration mistakes:
   - M1/M2 swapped.
   - motor polarity reversed.
   - left/right side swapped.
   - servo steering reversed.
   - servo center offset.
   - traction/yaw mismatch.
3. Keep testing safe by progressing through:
   - wheels-off-ground fixture.
   - low-power marked-floor tests.
   - full-speed optional confirmation.

## Required test equipment

- Robot under test with battery appropriate for the drive system.
- Robot controller board flashed with the current firmware.
- Mock controller / bench input source used by `tools/bench_e2e.py`.
- USB serial connection to the robot controller.
- Laptop/host on the robot AP/API network.
- Safe stand that holds the robot securely with wheels off the ground.
- Marked floor grid or taped test lane.
- Top-down or front-facing video recording.
- Notebook or test sheet for pass/fail observations.

Optional but useful:

- Tachometer app or slow-motion video for relative wheel speed.
- Current-limited bench supply for small test platforms.
- Wheel direction arrows taped to each wheel.
- Steering center/left/right marks for servo-steer bots.

## Safety checklist

Before every physical run:

- Weapon outputs disabled or physically disconnected.
- Robot restrained or wheels off ground for first motion test.
- Correct battery chemistry/cell count configured.
- Power Behavior configured for test:
  - GOOD = allow.
  - WARN = reduce.
  - LOW = disable.
- Controller failsafe tested on the bench.
- Clear emergency stop method known: power switch, battery unplug, or controller disconnect.
- No hands near wheels, belts, gears, or linkages during powered tests.

## Test artifact naming

Save serial logs and video with the same prefix:

```text
YYYYMMDD_robotname_layout_testname_serial.log
YYYYMMDD_robotname_layout_testname_video.mp4
```

Example:

```text
20260707_wedge2_2wheel_wheels-off-ground_serial.log
20260707_wedge2_2wheel_wheels-off-ground_video.mp4
```

## Layer 1: wheels-off-ground fixture

Purpose: validate wiring and direction without allowing the robot to drive away.

Setup:

1. Secure robot on stand.
2. Wheels must spin freely.
3. Connect battery.
4. Connect serial logging.
5. Start video recording with all wheels visible.
6. Run the firmware bench first:

```bash
.venv/bin/python tools/bench_e2e.py
```

Then perform physical drive-script commands manually or via a future `--physical-drive-script` mode.

### Universal wheels-off-ground matrix

| Input | Expected firmware telemetry | Expected physical behavior |
|---|---|---|
| neutral | M1/M2 `speed=0`, `dir=stop` | all wheels stopped |
| forward | M1/M2 nonzero same logical direction | robot wheels would move robot forward |
| reverse | M1/M2 nonzero opposite forward direction | robot wheels would move robot backward |
| left turn | left/right sides differ or oppose | robot would yaw left |
| right turn | left/right sides differ or oppose opposite left | robot would yaw right |
| brake | `drive_left=0`, `drive_right=0`, M1/M2 stop | all wheels stop |
| controller disconnect | M1/M2 stop | all wheels stop |
| battery WARN override | telemetry command about half of GOOD | visibly reduced wheel speed |
| battery LOW override | M1/M2 stop | all wheels stop |

Pass only if both telemetry and physical wheel behavior agree.

## Layer 2: marked-floor low-power test

Purpose: confirm real translation/yaw after wiring is correct.

Setup:

- Use a clear floor area with tape marks:
  - start box.
  - forward line.
  - left/right turn arcs.
  - stop zone.
- Start with low power:
  - WARN battery override if appropriate, or a reduced drive config.
  - short command durations, e.g. 0.5-1.0 s.

Run:

| Step | Input | Expected movement |
|---|---|---|
| 1 | forward pulse | moves straight forward |
| 2 | stop | stops promptly |
| 3 | reverse pulse | moves straight backward |
| 4 | left turn pulse | rotates/arcs left |
| 5 | right turn pulse | rotates/arcs right |
| 6 | forward + left | forward arc left |
| 7 | forward + right | forward arc right |
| 8 | disconnect while moving | stops safely |

Record drift/yaw and note if compensation is needed outside firmware, such as mechanical alignment or motor matching.

## 2-wheel differential bot checklist

Configuration:

```text
layout = differential
method = arcade or tank
M1 = left side
M2 = right side
```

Expected physical matrix:

| Command | M1 intent | M2 intent | Physical result |
|---|---|---|---|
| neutral | stop | stop | stopped |
| forward | forward direction | forward direction | straight forward |
| reverse | reverse direction | reverse direction | straight backward |
| left turn | left slower/reverse | right faster/forward | yaw left |
| right turn | left faster/forward | right slower/reverse | yaw right |
| brake | stop | stop | stopped |
| disconnect | stop | stop | stopped |

If forward drives backward:

- invert both M1 and M2, or swap motor leads consistently.

If forward spins in place:

- one side is reversed; invert that side only.

If left/right steering is swapped:

- swap M1/M2 side assignment or invert steering config.

## 4-wheel skid bot checklist

Configuration:

```text
layout = differential
method = arcade or tank
M1 = left motor group or left-side controller input
M2 = right motor group or right-side controller input
```

Physical expectations:

- Front-left and rear-left wheels spin the same direction for forward.
- Front-right and rear-right wheels spin the same direction for forward.
- Left and right groups cooperate for straight forward/reverse.
- Left/right groups oppose or differ correctly for yaw.

Wheels-off-ground matrix:

| Command | Left-front | Left-rear | Right-front | Right-rear | Expected result |
|---|---|---|---|---|---|
| forward | forward | forward | forward | forward | straight forward |
| reverse | reverse | reverse | reverse | reverse | straight backward |
| left turn | reverse/slow | reverse/slow | forward/fast | forward/fast | yaw left |
| right turn | forward/fast | forward/fast | reverse/slow | reverse/slow | yaw right |

If one wheel on a side fights the other, fix motor wiring/controller wiring before changing firmware mixing.

## Servo-steer bot checklist

Configuration:

```text
layout = servo_steering
method = servo_steering
M1 or M2 = drive motor output
S1 or S2 = steering servo output
```

Before powered floor tests:

1. Put robot on stand.
2. Mark steering linkage center.
3. Confirm neutral command gives center steering pulse and centered wheels.
4. Confirm left command moves wheels/linkage left.
5. Confirm right command moves wheels/linkage right.
6. Confirm throttle forward/reverse only drives propulsion motor.

Expected matrix:

| Command | Drive motor | Steering servo | Physical result |
|---|---|---|---|
| neutral | stop | center | stopped, wheels centered |
| forward | forward | center | straight forward |
| reverse | reverse | center | straight backward |
| steer left | stop or current throttle | left | points/turns left |
| steer right | stop or current throttle | right | points/turns right |
| forward + left | forward | left | forward arc left |
| forward + right | forward | right | forward arc right |
| brake | stop | center or safe configured state | stopped |
| disconnect | stop | safe/neutral | stopped/safe |

If steering is reversed:

- invert the steering output direction in config.

If center is mechanically off:

- adjust linkage first when possible.
- then tune servo center pulse if mechanical correction is insufficient.

## Proposed future script mode

Add a future operator-guided mode to the existing bench script:

```bash
.venv/bin/python tools/bench_e2e.py --physical-drive-script 2wheel
.venv/bin/python tools/bench_e2e.py --physical-drive-script 4wheel
.venv/bin/python tools/bench_e2e.py --physical-drive-script servo-steer
```

Each mode should:

1. Print the expected physical movement before each command.
2. Inject the controller input.
3. Log serial status showing drive/motor/servo intent.
4. Pause for human pass/fail observation.
5. Save a structured result file.

Suggested result record:

```json
{
  "robot": "name",
  "layout": "2wheel",
  "step": "forward",
  "telemetry_pass": true,
  "physical_pass": true,
  "notes": "tracks slightly right"
}
```

## Acceptance criteria

A robot configuration is physically validated when:

- `tools/bench_e2e.py` passes on the current firmware.
- Wheels-off-ground matrix passes.
- Marked-floor low-power matrix passes.
- Disconnect/failsafe stops physical motion.
- WARN behavior visibly reduces motion or commanded output.
- LOW behavior disables drive output.
- Any remaining quirks are documented as mechanical tuning, not firmware intent mismatch.
