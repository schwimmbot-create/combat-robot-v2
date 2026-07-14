# Schwimm Robot Board Arduino API

`SchwimmRobotBoard` is the supported beginner API for custom sketches. Values are clamped and outputs default safe. M1/M2 are brushed motor channels; S1/S2 are signal channels.

## Minimal arcade drive

```cpp
#include <SchwimmRobotBoard.h>
SchwimmRobotBoard robot;
void setup() { robot.begin(); robot.drive().setStyle(DriveStyle::Arcade); }
void loop() {
  robot.update();
  if (robot.controller().connected())
    robot.drive().arcade(robot.controller().leftY(), robot.controller().leftX()); // axes: -512..511
  else robot.stopAll();
}
```

## Tank drive

```cpp
robot.drive().tank(robot.controller().leftY(), robot.controller().rightY()); // -512..511
```

## Servo

```cpp
robot.servo(0).begin();                    // 0=S1, 1=S2
robot.servo(0).setRange(1000,1500,2000);  // microseconds
robot.servo(0).writeDegrees(90);           // clamped 0..180 degrees
```

## ESC

```cpp
robot.esc(1).begin(EscProtocol::OneShot125, false); // S2, forward-only
robot.esc(1).arm(); // explicit low→high→low sequence; call update() in loop
// Only after isArmed() becomes true:
robot.esc(1).setForwardPercent(25); // clamped 0..100%
```

Never attach a motor/weapon while validating an arming sequence for the first time. `setPercent()` remains safe until arming completes. OneShot42 and MultiShot use their documented pulse timing presets.

## Direct motor and power failsafe

```cpp
robot.motor(0).setPercent(-40); // M1, clamped -100..100%
if (robot.power().isWarning()) robot.motor(0).setPercent(-20);
if (robot.power().isLow()) robot.stopAll();
```

## Controller buttons

Use `ROBOT_BTN_A`, `ROBOT_BTN_B`, `ROBOT_BTN_X`, `ROBOT_BTN_Y`, `ROBOT_BTN_L1`, `ROBOT_BTN_R1`, `ROBOT_BTN_START`, and related constants with `button()`, `pressed()`, or `released()`.

## Persisted config

```cpp
robot.config().setMotorReversed(0, true); // setters write through to NVS
robot.config().setDriveStyle(DriveStyle::Tank);
robot.config().save();
```

Advanced users may still use internal classes, but those are not compatibility-stable and can bypass the documented safety model.
