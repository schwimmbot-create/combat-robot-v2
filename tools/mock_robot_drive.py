#!/usr/bin/env python
"""Mock robot drive simulator for combat-robot-v2.

This is a host-side mirror of the firmware drive math in:
  - components/myrobot/src/TaskManager.cpp
  - components/myrobot/src/Drive.cpp

It lets us verify controller values before putting the bot on blocks. Inputs are
already-normalized controller axes (-512..511-ish), matching ControllerState.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from enum import Enum

MAX_PWM = 255
RIGHTSIDE_UP = "rightside_up"
UPSIDE_DOWN = "upside_down"


class Orientation(str, Enum):
    RIGHTSIDE_UP = RIGHTSIDE_UP
    UPSIDE_DOWN = UPSIDE_DOWN


@dataclass(frozen=True)
class ControllerState:
    lx: int = 0
    ly: int = 0
    rx: int = 0
    ry: int = 0


def arduino_map(x: int, in_min: int, in_max: int, out_min: int, out_max: int) -> int:
    """Arduino map() semantics: integer arithmetic, truncating toward zero."""
    numerator = (x - in_min) * (out_max - out_min)
    denominator = in_max - in_min
    return int(numerator / denominator) + out_min


def constrain(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def motor(speed: int) -> dict[str, int | str]:
    pwm = constrain(abs(speed), 0, MAX_PWM)
    if pwm == 0:
        return {"direction": "stop", "pwm": 0}
    return {"direction": "reverse" if speed < 0 else "forward", "pwm": pwm}


def maybe_flip_for_upside_down(cmd: dict[str, int | str], orientation: Orientation) -> dict[str, int | str]:
    # DriveMotor::setSpeed flips FORWARD/REVERSE when orientation is upside-down.
    if orientation != Orientation.UPSIDE_DOWN or cmd["direction"] == "stop":
        return cmd
    return {
        "direction": "reverse" if cmd["direction"] == "forward" else "forward",
        "pwm": cmd["pwm"],
    }


def tank_split(gp: ControllerState, orientation: Orientation) -> tuple[int, int, dict[str, str]]:
    left = arduino_map(gp.ly, 511, -512, -MAX_PWM, MAX_PWM)
    right = arduino_map(gp.ry, 511, -512, -MAX_PWM, MAX_PWM)
    if orientation == Orientation.UPSIDE_DOWN:
        left, right = right, left
    return left, right, {"left": "LY", "right": "RY"}


def arcade(turn: int, throttle: int, orientation: Orientation) -> tuple[int, int]:
    x = arduino_map(turn, -512, 511, -MAX_PWM, MAX_PWM)
    y = arduino_map(throttle, 511, -512, -MAX_PWM, MAX_PWM)
    if orientation == Orientation.UPSIDE_DOWN:
        left = y - x
        right = y + x
    else:
        left = y + x
        right = y - x
    return left, right


def simulate_drive(
    gp: ControllerState,
    mode: str = "tank_split",
    orientation: Orientation | str = Orientation.RIGHTSIDE_UP,
) -> dict:
    if not isinstance(orientation, Orientation):
        orientation = Orientation(orientation)

    if mode == "tank_split":
        left_speed, right_speed, inputs = tank_split(gp, orientation)
    elif mode == "arcade_left":
        left_speed, right_speed = arcade(gp.lx, gp.ly, orientation)
        inputs = {"throttle": "LY", "turn": "LX"}
    elif mode == "arcade_right":
        left_speed, right_speed = arcade(gp.rx, gp.ry, orientation)
        inputs = {"throttle": "RY", "turn": "RX"}
    elif mode == "arcade_split":
        left_speed, right_speed = arcade(gp.rx, gp.ly, orientation)
        inputs = {"throttle": "LY", "turn": "RX"}
    else:
        raise ValueError(f"unknown drive mode: {mode}")

    left = maybe_flip_for_upside_down(motor(left_speed), orientation)
    right = maybe_flip_for_upside_down(motor(right_speed), orientation)
    return {
        "mode": mode,
        "orientation": orientation.value,
        "inputs": inputs,
        "left": left,
        "right": right,
        "raw": {"left_speed": left_speed, "right_speed": right_speed},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate combat robot drive output from controller axes.")
    parser.add_argument("--mode", default="tank_split", choices=["tank_split", "arcade_left", "arcade_right", "arcade_split"])
    parser.add_argument("--orientation", default=RIGHTSIDE_UP, choices=[RIGHTSIDE_UP, UPSIDE_DOWN])
    parser.add_argument("--lx", type=int, default=0)
    parser.add_argument("--ly", type=int, default=0)
    parser.add_argument("--rx", type=int, default=0)
    parser.add_argument("--ry", type=int, default=0)
    args = parser.parse_args()

    gp = ControllerState(lx=args.lx, ly=args.ly, rx=args.rx, ry=args.ry)
    print(json.dumps(simulate_drive(gp, args.mode, Orientation(args.orientation)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
