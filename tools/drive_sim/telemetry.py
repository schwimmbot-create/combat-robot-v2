from __future__ import annotations

from typing import Any

from .models import DifferentialCommand, ServoSteerCommand


def _motor_signed(speed: int, direction: str) -> float:
    value = max(0.0, min(1.0, speed / 255.0))
    if direction == "stop":
        return 0.0
    # Current firmware telemetry reports reverse for positive forward robot
    # commands in the existing DRV8871 polarity convention.
    return value if direction == "reverse" else -value


def differential_command_from_status(status: Any) -> DifferentialCommand:
    """Translate a bench RobotStatus-like object into normalized left/right sim command."""
    # Prefer semantic chassis telemetry when available. M1/M2 motor intent proves
    # driver output but board_config does not yet state which physical side each
    # motor is wired to, so using motor order for virtual left/right can invert
    # simulated turn direction on a real board.
    if hasattr(status, "drive_left") and hasattr(status, "drive_right"):
        return DifferentialCommand(
            max(-1.0, min(1.0, float(status.drive_left) / 511.0)),
            max(-1.0, min(1.0, float(status.drive_right) / 511.0)),
        )
    if hasattr(status, "m1_speed") and hasattr(status, "m2_speed"):
        return DifferentialCommand(
            _motor_signed(int(status.m1_speed), str(status.m1_dir)),
            _motor_signed(int(status.m2_speed), str(status.m2_dir)),
        )
    raise AttributeError("status must provide drive_left/drive_right or m1/m2 motor intent")


def servo_steer_command_from_status(status: Any, steering_output: str = "S1") -> ServoSteerCommand:
    throttle = differential_command_from_status(status).left
    pulse_attr = "s1_pulse_us" if steering_output.upper() == "S1" else "s2_pulse_us"
    return ServoSteerCommand(throttle=throttle, pulse_us=float(getattr(status, pulse_attr)))
