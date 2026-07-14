from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from drive_sim.assertions import ArcsLeft, ArcsRight, EndsStopped, HoldsStill, MovesBackward, MovesForward, TurnsLeft, TurnsRight
from drive_sim.models import DifferentialCommand, DifferentialRobot, FourWheelSkidRobot, ServoSteerCommand, ServoSteerRobot
from drive_sim.render import render_report
from drive_sim.scenarios import run_demo_scenarios


def test_differential_forward_reverse_and_stop():
    robot = DifferentialRobot()
    traj = robot.run([(DifferentialCommand(0.7, 0.7), 1.0), (DifferentialCommand(0, 0), 0.2)])
    assert MovesForward().check(traj).passed
    assert EndsStopped().check(traj).passed

    robot = DifferentialRobot()
    traj = robot.run([(DifferentialCommand(-0.7, -0.7), 1.0), (DifferentialCommand(0, 0), 0.2)])
    assert MovesBackward().check(traj).passed
    assert EndsStopped().check(traj).passed


def test_differential_turns_left_and_right():
    left = DifferentialRobot().run([(DifferentialCommand(-0.45, 0.45), 0.45), (DifferentialCommand(0, 0), 0.2)])
    right = DifferentialRobot().run([(DifferentialCommand(0.45, -0.45), 0.45), (DifferentialCommand(0, 0), 0.2)])
    assert TurnsLeft().check(left).passed
    assert TurnsRight().check(right).passed
    assert EndsStopped().check(left).passed
    assert EndsStopped().check(right).passed


def test_four_wheel_skid_uses_left_right_side_groups():
    cmd = DifferentialCommand(0.25, 0.75)
    wheels = FourWheelSkidRobot.wheel_commands(cmd)
    assert wheels == {
        "left_front": 0.25,
        "left_rear": 0.25,
        "right_front": 0.75,
        "right_rear": 0.75,
    }
    traj = FourWheelSkidRobot().run([(cmd, 0.5), (DifferentialCommand(0, 0), 0.2)])
    assert ArcsLeft().check(traj).passed
    assert EndsStopped().check(traj).passed


def test_servo_steer_center_left_right_and_no_throttle():
    center = ServoSteerRobot().run([(ServoSteerCommand(0.7, 1500), 1.0), (ServoSteerCommand(0, 1500), 0.2)])
    assert MovesForward().check(center).passed
    assert EndsStopped().check(center).passed

    left = ServoSteerRobot().run([(ServoSteerCommand(0.65, 1000), 0.8), (ServoSteerCommand(0, 1500), 0.2)])
    right = ServoSteerRobot().run([(ServoSteerCommand(0.65, 2000), 0.8), (ServoSteerCommand(0, 1500), 0.2)])
    assert ArcsLeft().check(left).passed
    assert ArcsRight().check(right).passed

    still = ServoSteerRobot().run([(ServoSteerCommand(0, 1000), 1.0), (ServoSteerCommand(0, 1500), 0.2)])
    assert HoldsStill().check(still).passed
    assert EndsStopped().check(still).passed


def test_demo_scenarios_all_pass():
    results = run_demo_scenarios()
    assert len(results) >= 10
    assert all(result.passed for result in results), [
        (result.name, [(check.name, check.passed, check.detail) for check in result.assertion_results])
        for result in results
        if not result.passed
    ]


def test_render_report_writes_self_contained_html(tmp_path: Path):
    results = run_demo_scenarios()
    out = render_report(results, tmp_path / "drive-sim.html")
    html = out.read_text()
    assert "Virtual Drive Simulator Report" in html
    assert "2wheel_forward_then_stop" in html
    assert "<svg" in html
    assert "PASS" in html
