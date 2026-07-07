# Combat Robot Controller — Four-Channel Robotic Use Case Configurations

## Overview

The controller exposes four current output channels: **M1, M2, S1, S2**.

- **M1/M2** are drive motor channels only for board v2 configuration.
- **S1/S2** are auxiliary servo/accessory channels. Weapon-like behavior is configured as a purpose/role on S1 or S2; there is no dedicated Weapon output and old Weapon configs are not migrated.

Each channel can carry purpose/protocol/semantics, controller source mapping, direction or polarity, failsafe, and power-behavior metadata. S1/S2 additionally stress servo, ESC/weapon ESC, digital output, digital input, and PWM accessory roles.

---

## Compact Configuration Matrix

| Use Case | M1 | M2 | S1 | S2 | Drive Mode | Key Tradeoff |
|---|---|---|---|---|---|---|
| **1. Beetleweight combat bot (tank)** | drive / left tank | drive / right tank | disabled / accessory | esc + weapon_safety / RT | `tank_split` | Weapon consumes one aux channel |
| **2. Beetleweight combat bot (arcade)** | drive / left side | drive / right side | disabled / accessory | esc + weapon_safety / RT | `arcade_split` | Same weapon role, different drive mixer |
| **3. Tracked flipper + self-right** | drive / left tank | drive / right tank | esc + weapon_safety flipper / Y | digital_output self-right / L3 | `tank_split` | Both aux channels consumed |
| **4. Small arm/gripper** | drive-only / unavailable for arm | drive-only / unavailable for arm | servo joint | servo/gripper | `disabled` or parked | Board v2 only has two aux servo channels |
| **5. FPV camera rover** | drive | drive | pan servo | tilt servo or camera power | `arcade_split` | No spare channel if both pan and tilt are used |
| **6. Sumo + line follower** | drive / left | drive / right | digital_input edge sensor | digital_input edge sensor | `tank_split` | No room for an udge/spike output unless one sensor is removed |
| **7. RC boat/accessory** | left prop drive | right prop drive | disabled / accessory | pwm_accessory pump/lights | `arcade_split` | Aux channels are accessories only |
| **8. Animatronic/prop controller** | drive-only / unused | drive-only / unused | servo or digital_output | servo or digital_output | `disabled` | Only two expressive aux channels on board v2 |
| **9. E-stop accessory** | drive-only / unused | drive-only / unused | digital_output safety relay | disabled | `disabled` | Safety role must live on a real channel, not Weapon |

---

## Detailed Use-Case Notes

### 1. Beetleweight Combat Robot — Tank Drive

- **M1**: `purpose=drive`, primary `LY`, direction per wiring.
- **M2**: `purpose=drive`, primary `RY`, direction usually reversed for mirrored drivetrain.
- **S2**: `purpose=esc + weapon_safety`, protocol `oneshot125` or `rc_esc_pwm`, semantics `esc_forward_only` or `esc_bidirectional`, primary `RT`.
- **S1**: spare, disabled, or accessory.
- **Safety**: weapon role uses `weapon_mode=deadman_only`, `deadman_source=L1`, LOW battery defaults to disable.
- **UI expectation**: no Weapon card; S2 card can be labeled “Weapon” and shows weapon-role controls.

### 2. Beetleweight Combat Robot — Arcade Drive

- **M1/M2**: drive-only channels controlled by arcade mixer, e.g. `LY` throttle + `RX` turn.
- **S2**: weapon ESC role as above.
- **UI expectation**: drive mode selector explains input reservation; aux channel warnings should flag reuse of drive sources by S1/S2.

### 3. Tracked Robot with Flipper and Self-Righting

- **M1/M2**: tank drive.
- **S1**: `purpose=esc + weapon_safety`, primary `Y`, `weapon_mode=arming_and_deadman`, `arming_source=B`, `deadman_source=L1`, low ramp for fast flipper response.
- **S2**: `purpose=digital_output`, primary `L3`, active-high MOSFET/solenoid output, safe default off.
- **Tradeoff**: all four channels are used; there is no extra output for LEDs/camera without changing the setup.

### 4. Small Arm / Gripper

- **M1/M2**: remain drive-only and should not be repurposed as servos on board v2.
- **S1/S2**: can drive up to two servo-style functions, e.g. shoulder + gripper, or pan + grip.
- **Gap**: a 4-DOF arm needs more channels than this board provides. UI should show channel-budget warnings rather than implying M1/M2 can be reassigned.

### 5. FPV Camera Rover

- **M1/M2**: drive.
- **S1**: camera pan servo.
- **S2**: camera tilt servo, or digital/PWM camera power, but not both at once.
- **Gap**: source conflicts are easy; `LY`/`RX` may already be consumed by drive mode, so UI should warn before assigning those to pan/tilt.

### 6. Sumo + Line-Follower Hybrid

- **M1/M2**: drive.
- **S1/S2**: digital inputs for left/right edge sensors.
- **Tradeoff**: adding an udge/spike output requires sacrificing one sensor or external hardware.
- **UI expectation**: digital input polarity plus live monitor/status for S1/S2.

### 7. Differential-Thrust RC Boat

- **M1/M2**: left/right prop drive.
- **S2**: `purpose=pwm_accessory` or digital output for bilge pump/lights.
- **S1**: spare/accessory.
- **UI expectation**: PWM accessory frequency/duty fields and LOW battery policy.

### 8. Animatronic / Prop

- **M1/M2**: drive-only, generally unused/parked.
- **S1/S2**: two expressive channels: servo jaw/eye movement, digital LEDs, or PWM dimming.
- **Gap**: the board is not a many-channel prop controller; UI should make the two-aux-channel budget obvious.

### 9. E-stop / Safety Relay Accessory

- **S1 or S2**: `purpose=digital_output`, safety-critical display name, default safe state.
- **M1/M2**: unused or parked drive channels.
- **UI expectation**: safety-critical changes require warnings; battery policy should not silently disable a safety relay unless explicitly configured.

---

## Current Gaps to Track

1. Remove all old top-level `Weapon` channel assumptions from schema, UI, runtime, export/import, tests, and docs.
2. Keep M1/M2 drive-only in UI and runtime scope.
3. Make S1/S2 role-based aux channels.
4. Add weapon-role controls on S1/S2, not a separate card.
5. Add source conflict and channel budget warnings.
6. Reject/drop old `Weapon` configs rather than migrating them.
7. Align runtime with saved S1/S2 roles.
8. Add digital input status for S1/S2.
9. Expand bench E2E around S1/S2 roles and safety flows.
