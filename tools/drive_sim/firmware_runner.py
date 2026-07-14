from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal

from .assertions import MovementAssertion, check_all
from .board_data import BoardData
from .models import DifferentialRobot, FourWheelSkidRobot, ServoSteerRobot, Trajectory
from .scenarios import RobotKind, ScenarioResult
from .telemetry import differential_command_from_status, servo_steer_command_from_status


@dataclass(frozen=True)
class TimedStatus:
    t_s: float
    status: Any


def _durations(samples: list[TimedStatus]) -> Iterable[tuple[Any, float]]:
    for idx, sample in enumerate(samples):
        if idx + 1 < len(samples):
            dt = samples[idx + 1].t_s - sample.t_s
        elif idx > 0:
            dt = samples[idx].t_s - samples[idx - 1].t_s
        else:
            dt = 0.02
        yield sample.status, max(0.0, dt)


def simulate_status_samples(
    *,
    name: str,
    kind: RobotKind,
    samples: list[TimedStatus],
    assertions: list[MovementAssertion],
    board: BoardData,
    description: str = "",
    steering_output: Literal["S1", "S2"] = "S1",
) -> ScenarioResult:
    if not samples:
        raise ValueError("at least one timed status sample is required")

    if kind == "servo_steer":
        robot = ServoSteerRobot(
            wheel_base_m=board.servo_wheel_base_m,
            max_speed_mps=board.max_speed_mps,
            max_steering_angle_deg=board.max_steering_angle_deg,
        )
        for status, dt in _durations(samples):
            robot.step(servo_steer_command_from_status(status, steering_output=steering_output), dt)
    elif kind == "four_wheel_skid":
        robot = FourWheelSkidRobot(wheel_base_m=board.track_width_m, max_speed_mps=board.max_speed_mps)
        for status, dt in _durations(samples):
            robot.step(differential_command_from_status(status), dt)
    elif kind == "differential":
        robot = DifferentialRobot(wheel_base_m=board.track_width_m, max_speed_mps=board.max_speed_mps)
        for status, dt in _durations(samples):
            robot.step(differential_command_from_status(status), dt)
    else:
        raise ValueError(f"unknown robot kind: {kind}")

    trajectory: Trajectory = robot.trajectory
    return ScenarioResult(name, kind, trajectory, check_all(trajectory, assertions), description)
