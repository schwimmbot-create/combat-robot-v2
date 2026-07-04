"""Host-side mock robot drive tests.

These tests pin the controller-value -> mock-motor-output contract used by
both the CLI simulator and the HTML mock robot preview. They intentionally
mirror the firmware Drive.cpp math: Y-up is negative from HID decode, then
setForwardInputLimits(511, -512) makes negative Y become FORWARD PWM.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from mock_robot_drive import ControllerState, Orientation, simulate_drive  # noqa: E402


CENTER = 0
UP = -508
DOWN = 512
LEFT = -512
RIGHT = 511


def directions(result):
    return result["left"]["direction"], result["right"]["direction"]


def pwm(result):
    return result["left"]["pwm"], result["right"]["pwm"]


@pytest.mark.parametrize("mode", ["tank_split", "arcade_left", "arcade_right", "arcade_split"])
def test_stick_up_drives_mock_robot_forward_for_each_mode(mode):
    gp = ControllerState(ly=UP, ry=UP, lx=CENTER, rx=CENTER)
    out = simulate_drive(gp, mode)

    assert directions(out) == ("forward", "forward")
    assert pwm(out)[0] > 240
    assert pwm(out)[1] > 240


def test_tank_split_maps_left_and_right_sticks_to_their_own_sides():
    gp = ControllerState(ly=UP, ry=DOWN, lx=RIGHT, rx=LEFT)
    out = simulate_drive(gp, "tank_split")

    assert out["left"] == {"direction": "forward", "pwm": 253}
    assert out["right"] == {"direction": "reverse", "pwm": 255}


def test_arcade_left_uses_left_stick_y_for_speed_and_left_stick_x_for_turn():
    gp = ControllerState(ly=UP, ry=DOWN, lx=RIGHT, rx=LEFT)
    out = simulate_drive(gp, "arcade_left")

    assert out["left"]["direction"] == "forward"
    assert out["right"]["pwm"] < out["left"]["pwm"]
    assert out["inputs"] == {"throttle": "LY", "turn": "LX"}


def test_arcade_right_uses_right_stick_y_for_speed_and_right_stick_x_for_turn():
    gp = ControllerState(ly=DOWN, ry=UP, lx=LEFT, rx=RIGHT)
    out = simulate_drive(gp, "arcade_right")

    assert out["left"]["direction"] == "forward"
    assert out["right"]["pwm"] < out["left"]["pwm"]
    assert out["inputs"] == {"throttle": "RY", "turn": "RX"}


def test_arcade_split_uses_left_y_for_speed_and_right_x_for_turn():
    gp = ControllerState(ly=UP, ry=DOWN, lx=LEFT, rx=RIGHT)
    out = simulate_drive(gp, "arcade_split")

    assert out["left"]["direction"] == "forward"
    assert out["right"]["pwm"] < out["left"]["pwm"]
    assert out["inputs"] == {"throttle": "LY", "turn": "RX"}


def test_upside_down_orientation_swaps_sides_and_flips_motor_direction_like_firmware():
    # Drive.cpp swaps left/right speeds when upside-down, then
    # DriveMotor::setSpeed flips FORWARD/REVERSE for orientation.
    gp = ControllerState(ly=UP, ry=DOWN)
    out = simulate_drive(gp, "tank_split", orientation=Orientation.UPSIDE_DOWN)

    assert out["left"] == {"direction": "forward", "pwm": 255}
    assert out["right"] == {"direction": "reverse", "pwm": 253}


def test_mock_robot_cli_outputs_json_for_controller_values():
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "mock_robot_drive.py"),
        "--mode", "arcade_split",
        "--ly", str(UP),
        "--rx", str(RIGHT),
    ]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    out = json.loads(completed.stdout)

    assert out["mode"] == "arcade_split"
    assert out["inputs"] == {"throttle": "LY", "turn": "RX"}
    assert out["left"]["direction"] == "forward"
    assert out["right"]["pwm"] < out["left"]["pwm"]
