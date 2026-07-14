from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .assertions import ArcsLeft, ArcsRight, EndsStopped, HoldsStill, MovesBackward, MovesForward, MovementAssertion, TurnsLeft, TurnsRight, check_all
from .board_data import BoardData
from .models import DifferentialCommand, DifferentialRobot, FourWheelSkidRobot, ServoSteerCommand, ServoSteerRobot, Trajectory

RobotKind = Literal["differential", "four_wheel_skid", "servo_steer"]


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    kind: RobotKind
    trajectory: Trajectory
    assertion_results: list
    description: str = ""

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.assertion_results)


@dataclass(frozen=True)
class Scenario:
    name: str
    kind: RobotKind
    steps: list[tuple[object, float]]
    assertions: list[MovementAssertion]
    description: str = ""
    board: BoardData | None = None

    def run(self, dt_s: float = 0.02) -> ScenarioResult:
        if self.kind == "differential":
            robot = DifferentialRobot(
                wheel_base_m=self.board.track_width_m if self.board else 0.18,
                max_speed_mps=self.board.max_speed_mps if self.board else 1.0,
            )
        elif self.kind == "four_wheel_skid":
            robot = FourWheelSkidRobot(
                wheel_base_m=self.board.track_width_m if self.board else 0.18,
                max_speed_mps=self.board.max_speed_mps if self.board else 1.0,
            )
        elif self.kind == "servo_steer":
            robot = ServoSteerRobot(
                wheel_base_m=self.board.servo_wheel_base_m if self.board else 0.22,
                max_speed_mps=self.board.max_speed_mps if self.board else 1.0,
                max_steering_angle_deg=self.board.max_steering_angle_deg if self.board else 35.0,
            )
        else:
            raise ValueError(f"unknown robot kind: {self.kind}")
        trajectory = robot.run(self.steps, dt_s=dt_s)  # type: ignore[arg-type]
        return ScenarioResult(self.name, self.kind, trajectory, check_all(trajectory, self.assertions), self.description)


def demo_scenarios() -> list[Scenario]:
    stop = DifferentialCommand(0.0, 0.0)
    servo_stop = ServoSteerCommand(0.0, 1500)
    return [
        Scenario(
            name="2wheel_forward_then_stop",
            kind="differential",
            description="Equal left/right commands should drive straight forward and end stopped.",
            steps=[(DifferentialCommand(0.7, 0.7), 1.0), (stop, 0.2)],
            assertions=[MovesForward(), EndsStopped()],
        ),
        Scenario(
            name="2wheel_reverse_then_stop",
            kind="differential",
            description="Equal negative left/right commands should drive straight backward.",
            steps=[(DifferentialCommand(-0.7, -0.7), 1.0), (stop, 0.2)],
            assertions=[MovesBackward(), EndsStopped()],
        ),
        Scenario(
            name="2wheel_left_spin",
            kind="differential",
            description="Left side reverse, right side forward should rotate left.",
            steps=[(DifferentialCommand(-0.45, 0.45), 0.45), (stop, 0.2)],
            assertions=[TurnsLeft(), EndsStopped()],
        ),
        Scenario(
            name="2wheel_right_spin",
            kind="differential",
            description="Left side forward, right side reverse should rotate right.",
            steps=[(DifferentialCommand(0.45, -0.45), 0.45), (stop, 0.2)],
            assertions=[TurnsRight(), EndsStopped()],
        ),
        Scenario(
            name="4wheel_skid_left_arc",
            kind="four_wheel_skid",
            description="4-wheel skid is modeled as left/right side groups; faster right side arcs left.",
            steps=[(DifferentialCommand(0.25, 0.75), 0.5), (stop, 0.2)],
            assertions=[ArcsLeft(), EndsStopped()],
        ),
        Scenario(
            name="4wheel_skid_right_arc",
            kind="four_wheel_skid",
            description="Faster left side arcs right.",
            steps=[(DifferentialCommand(0.75, 0.25), 0.5), (stop, 0.2)],
            assertions=[ArcsRight(), EndsStopped()],
        ),
        Scenario(
            name="servo_steer_forward_center",
            kind="servo_steer",
            description="Centered steering pulse should drive straight forward.",
            steps=[(ServoSteerCommand(0.7, 1500), 1.0), (servo_stop, 0.2)],
            assertions=[MovesForward(), EndsStopped()],
        ),
        Scenario(
            name="servo_steer_left_arc",
            kind="servo_steer",
            description="Low pulse steers left while throttle is forward.",
            steps=[(ServoSteerCommand(0.65, 1000), 0.8), (servo_stop, 0.2)],
            assertions=[ArcsLeft(), EndsStopped()],
        ),
        Scenario(
            name="servo_steer_right_arc",
            kind="servo_steer",
            description="High pulse steers right while throttle is forward.",
            steps=[(ServoSteerCommand(0.65, 2000), 0.8), (servo_stop, 0.2)],
            assertions=[ArcsRight(), EndsStopped()],
        ),
        Scenario(
            name="servo_steer_without_throttle_holds_position",
            kind="servo_steer",
            description="Steering alone should not translate the robot.",
            steps=[(ServoSteerCommand(0.0, 1000), 1.0), (servo_stop, 0.2)],
            assertions=[HoldsStill(), EndsStopped()],
        ),
    ]


def run_demo_scenarios(dt_s: float = 0.02) -> list[ScenarioResult]:
    return [scenario.run(dt_s=dt_s) for scenario in demo_scenarios()]


def board_scenarios(board: BoardData) -> list[Scenario]:
    stop = DifferentialCommand(0.0, 0.0)
    servo_stop = ServoSteerCommand(0.0, 1500)
    scenarios = [
        Scenario(
            name=f"board{board.rev}_{board.chassis_kind}_forward_then_stop",
            kind=board.chassis_kind,  # type: ignore[arg-type]
            description=f"{board.summary}: equal side commands should drive straight forward.",
            board=board,
            steps=[(DifferentialCommand(0.7, 0.7), 1.0), (stop, 0.2)],
            assertions=[MovesForward(), EndsStopped()],
        ),
        Scenario(
            name=f"board{board.rev}_{board.chassis_kind}_left_arc",
            kind=board.chassis_kind,  # type: ignore[arg-type]
            description=f"{board.summary}: faster right side should arc left.",
            board=board,
            steps=[(DifferentialCommand(0.25, 0.75), 0.5), (stop, 0.2)],
            assertions=[ArcsLeft(), EndsStopped()],
        ),
        Scenario(
            name=f"board{board.rev}_{board.chassis_kind}_right_arc",
            kind=board.chassis_kind,  # type: ignore[arg-type]
            description=f"{board.summary}: faster left side should arc right.",
            board=board,
            steps=[(DifferentialCommand(0.75, 0.25), 0.5), (stop, 0.2)],
            assertions=[ArcsRight(), EndsStopped()],
        ),
        Scenario(
            name=f"board{board.rev}_servo_steer_forward_center",
            kind="servo_steer",
            description=f"{board.summary}: centered steering pulse should drive straight forward.",
            board=board,
            steps=[(ServoSteerCommand(0.7, 1500), 1.0), (servo_stop, 0.2)],
            assertions=[MovesForward(), EndsStopped()],
        ),
        Scenario(
            name=f"board{board.rev}_servo_steer_left_arc",
            kind="servo_steer",
            description=f"{board.summary}: low steering pulse should arc left.",
            board=board,
            steps=[(ServoSteerCommand(0.65, 1000), 0.8), (servo_stop, 0.2)],
            assertions=[ArcsLeft(), EndsStopped()],
        ),
        Scenario(
            name=f"board{board.rev}_servo_steer_right_arc",
            kind="servo_steer",
            description=f"{board.summary}: high steering pulse should arc right.",
            board=board,
            steps=[(ServoSteerCommand(0.65, 2000), 0.8), (servo_stop, 0.2)],
            assertions=[ArcsRight(), EndsStopped()],
        ),
    ]
    return scenarios


def run_board_scenarios(board: BoardData, dt_s: float = 0.02) -> list[ScenarioResult]:
    return [scenario.run(dt_s=dt_s) for scenario in board_scenarios(board)]
