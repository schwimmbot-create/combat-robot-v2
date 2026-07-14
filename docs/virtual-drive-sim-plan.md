# Virtual Drive Simulator Plan

The current hardware bench proves firmware command intent: controller input plus configuration produces expected `drive_left`, `drive_right`, M1/M2 motor intent, S1/S2 pulse intent, power behavior, and failsafe behavior. The virtual drive simulator adds the next layer: feed those commands into simple robot kinematics and verify that the robot would move in the intended direction.

## Scope

This simulator is a deterministic drive-logic validator, not a high-fidelity physics engine.

It models:

- differential/2-wheel motion from left/right commands.
- 4-wheel skid motion as left/right side groups.
- servo-steer motion with a bicycle model from throttle plus servo pulse.
- movement classes: forward, reverse, left/right turn, left/right arc, stopped, holds still.
- visual top-down trajectory reports.

It intentionally does not model:

- traction loss, wheel slip, impact loads, battery sag, gearbox backlash, center of mass, floor friction, or servo linkage binding.

## Architecture

```text
tools/drive_sim/
  __init__.py
  board_data.py      # parses components/board_config/include/board_config.h
  models.py          # kinematic models and trajectory primitives
  assertions.py      # movement classifiers/assertions
  scenarios.py       # reusable scenario definitions
  render.py          # self-contained HTML/SVG trajectory reports
  cli.py             # demo/standalone runner

tests/unit/test_drive_sim.py
tests/unit/test_drive_sim_board_data.py
tests/unit/test_drive_sim_telemetry.py
```

`board_data.py` reads the actual firmware board data from
`components/board_config/include/board_config.h`. `BOARD_REV=2` maps to the current
2-motor production board and defaults to a differential model. `BOARD_REV=3` maps
to the designed 4-motor board and defaults to a four-wheel skid model. Physical
dimensions are conservative simulator defaults until robot-specific chassis data is
added; the electronics topology comes from the real board config.
Hardware-bench integration:

```text
tools/bench_e2e.py --drive-sim
```

The future hardware-backed mode should:

1. configure firmware drive mode.
2. inject HID inputs through `/api/bench/hid`.
3. collect serial `RobotStatus` samples.
4. translate telemetry to simulator commands.
5. simulate motion over time.
6. assert expected movement class.
7. generate an HTML/SVG report.

## Data model

Simulator state:

```text
Pose(x_m, y_m, theta_rad)
Trajectory(samples=[TrajectorySample(t_s, pose, linear_velocity, angular_velocity)])
```

Commands:

```text
DifferentialCommand(left, right)       # normalized -1..1
ServoSteerCommand(throttle, pulse_us)  # throttle -1..1 plus servo pulse
```

## Differential / 2-wheel model

For M1/M2 left/right commands:

```text
v_left  = left_command  * max_speed_mps
v_right = right_command * max_speed_mps
v       = (v_left + v_right) / 2
omega   = (v_right - v_left) / wheel_base_m
x      += v * cos(theta) * dt
y      += v * sin(theta) * dt
theta  += omega * dt
```

## 4-wheel skid model

The first version uses the same differential kinematics because firmware exposes left/right side intent. It labels side groups explicitly:

```text
left_front = left_rear = left_command
right_front = right_rear = right_command
```

This catches logical left/right/forward/reverse mistakes while documenting that real skid-steer traction is approximate.

## Servo-steer model

For servo-steer bots:

```text
steering_angle = pulse_us mapped from min/center/max to -max_angle..+max_angle
v              = throttle * max_speed_mps
omega          = v / wheel_base_m * tan(steering_angle)
x             += v * cos(theta) * dt
y             += v * sin(theta) * dt
theta         += omega * dt
```

## Movement classifiers

The simulator should assert movement categories rather than exact poses:

- `MovesForward`
- `MovesBackward`
- `TurnsLeft`
- `TurnsRight`
- `ArcsLeft`
- `ArcsRight`
- `EndsStopped`
- `HoldsStill`

This catches sign/polarity/mixing mistakes without overfitting exact physical dimensions.

## Initial scenarios

Differential / 2-wheel:

- forward
- reverse
- spin/turn left
- spin/turn right
- left arc
- right arc
- brake/hold still

4-wheel skid:

- forward
- reverse
- left turn
- right turn
- brake/hold still

Servo-steer:

- forward with centered steering
- reverse with centered steering
- forward left arc
- forward right arc
- steer without throttle holds position
- brake/hold still

## Visual report

The renderer should generate a self-contained HTML file with inline SVG:

```text
artifacts/drive-sim/latest.html
```

Each scenario card should show:

- path trace.
- start/end markers.
- heading arrows.
- expected movement labels.
- measured distance/heading/final-speed metrics.
- PASS/FAIL badge.

## Acceptance criteria

Phase 1 is complete when:

```bash
.venv/bin/python -m pytest tests/unit/test_drive_sim.py -q
PYTHONPATH=tools .venv/bin/python -m drive_sim.cli --board-rev 2 --out artifacts/drive-sim/latest.html
```

both pass and the generated report renders in a browser.

Phase 2 integration command:

```bash
.venv/bin/python tools/bench_e2e.py --drive-sim-only --drive-sim-out artifacts/drive-sim/bench-live.html
```

`--drive-sim` runs the live-telemetry simulator after the normal API bench.
`--drive-sim-only` runs liveness/link setup plus only the live simulator scenarios.
Both modes collect real serial `RobotStatus` samples, convert them through
`tools/drive_sim/telemetry.py`, simulate motion, assert movement class, and write a
self-contained HTML trajectory report.
