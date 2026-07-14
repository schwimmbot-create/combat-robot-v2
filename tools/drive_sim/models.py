from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, cos, degrees, pi, radians, sin, tan
from typing import Iterable


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def wrap_angle_rad(angle: float) -> float:
    while angle > pi:
        angle -= 2 * pi
    while angle < -pi:
        angle += 2 * pi
    return angle


@dataclass(frozen=True)
class Pose:
    x_m: float = 0.0
    y_m: float = 0.0
    theta_rad: float = 0.0

    @property
    def theta_deg(self) -> float:
        return degrees(self.theta_rad)


@dataclass(frozen=True)
class TrajectorySample:
    t_s: float
    pose: Pose
    linear_velocity_mps: float = 0.0
    angular_velocity_radps: float = 0.0


@dataclass
class Trajectory:
    samples: list[TrajectorySample] = field(default_factory=list)

    def add(self, sample: TrajectorySample) -> None:
        self.samples.append(sample)

    @property
    def start(self) -> Pose:
        return self.samples[0].pose if self.samples else Pose()

    @property
    def end(self) -> Pose:
        return self.samples[-1].pose if self.samples else Pose()

    @property
    def duration_s(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        return self.samples[-1].t_s - self.samples[0].t_s

    @property
    def displacement_m(self) -> float:
        dx = self.end.x_m - self.start.x_m
        dy = self.end.y_m - self.start.y_m
        return (dx * dx + dy * dy) ** 0.5

    @property
    def forward_displacement_m(self) -> float:
        dx = self.end.x_m - self.start.x_m
        dy = self.end.y_m - self.start.y_m
        return dx * cos(self.start.theta_rad) + dy * sin(self.start.theta_rad)

    @property
    def lateral_displacement_m(self) -> float:
        dx = self.end.x_m - self.start.x_m
        dy = self.end.y_m - self.start.y_m
        return -dx * sin(self.start.theta_rad) + dy * cos(self.start.theta_rad)

    @property
    def heading_delta_rad(self) -> float:
        return wrap_angle_rad(self.end.theta_rad - self.start.theta_rad)

    @property
    def heading_delta_deg(self) -> float:
        return degrees(self.heading_delta_rad)

    @property
    def final_speed_mps(self) -> float:
        return abs(self.samples[-1].linear_velocity_mps) if self.samples else 0.0

    def metrics(self) -> dict[str, float]:
        return {
            "duration_s": self.duration_s,
            "displacement_m": self.displacement_m,
            "forward_displacement_m": self.forward_displacement_m,
            "lateral_displacement_m": self.lateral_displacement_m,
            "heading_delta_deg": self.heading_delta_deg,
            "final_speed_mps": self.final_speed_mps,
        }


@dataclass(frozen=True)
class DifferentialCommand:
    left: float
    right: float

    def normalized(self) -> "DifferentialCommand":
        return DifferentialCommand(clamp(self.left, -1.0, 1.0), clamp(self.right, -1.0, 1.0))


@dataclass(frozen=True)
class ServoSteerCommand:
    throttle: float
    pulse_us: float

    def normalized(self) -> "ServoSteerCommand":
        return ServoSteerCommand(clamp(self.throttle, -1.0, 1.0), self.pulse_us)


@dataclass
class DifferentialRobot:
    wheel_base_m: float = 0.18
    max_speed_mps: float = 1.0
    pose: Pose = field(default_factory=Pose)
    t_s: float = 0.0
    trajectory: Trajectory = field(default_factory=Trajectory)

    def __post_init__(self) -> None:
        if not self.trajectory.samples:
            self.trajectory.add(TrajectorySample(self.t_s, self.pose))

    def step(self, command: DifferentialCommand, dt_s: float) -> Pose:
        cmd = command.normalized()
        v_left = cmd.left * self.max_speed_mps
        v_right = cmd.right * self.max_speed_mps
        v = (v_left + v_right) / 2.0
        omega = (v_right - v_left) / self.wheel_base_m
        theta_mid = self.pose.theta_rad + omega * dt_s / 2.0
        x = self.pose.x_m + v * cos(theta_mid) * dt_s
        y = self.pose.y_m + v * sin(theta_mid) * dt_s
        theta = wrap_angle_rad(self.pose.theta_rad + omega * dt_s)
        self.t_s += dt_s
        self.pose = Pose(x, y, theta)
        self.trajectory.add(TrajectorySample(self.t_s, self.pose, v, omega))
        return self.pose

    def run(self, steps: Iterable[tuple[DifferentialCommand, float]], dt_s: float = 0.02) -> Trajectory:
        for command, duration_s in steps:
            remaining = duration_s
            while remaining > 1e-9:
                dt = min(dt_s, remaining)
                self.step(command, dt)
                remaining -= dt
        return self.trajectory


@dataclass
class FourWheelSkidRobot(DifferentialRobot):
    """Four-wheel skid model represented as left/right side groups.

    The first-order kinematics are differential-drive. This is intentional: it validates
    firmware drive logic and side grouping without pretending to model traction/slip.
    """

    @staticmethod
    def wheel_commands(command: DifferentialCommand) -> dict[str, float]:
        cmd = command.normalized()
        return {
            "left_front": cmd.left,
            "left_rear": cmd.left,
            "right_front": cmd.right,
            "right_rear": cmd.right,
        }


@dataclass
class ServoSteerRobot:
    wheel_base_m: float = 0.22
    max_speed_mps: float = 1.0
    min_pulse_us: float = 1000.0
    center_pulse_us: float = 1500.0
    max_pulse_us: float = 2000.0
    max_steering_angle_deg: float = 35.0
    pose: Pose = field(default_factory=Pose)
    t_s: float = 0.0
    trajectory: Trajectory = field(default_factory=Trajectory)

    def __post_init__(self) -> None:
        if not self.trajectory.samples:
            self.trajectory.add(TrajectorySample(self.t_s, self.pose))

    def steering_angle_rad(self, pulse_us: float) -> float:
        if pulse_us <= self.center_pulse_us:
            denom = max(1.0, self.center_pulse_us - self.min_pulse_us)
            ratio = (pulse_us - self.center_pulse_us) / denom
        else:
            denom = max(1.0, self.max_pulse_us - self.center_pulse_us)
            ratio = (pulse_us - self.center_pulse_us) / denom
        # Firmware/UI convention: lower-than-center steering pulse is "left" and
        # higher-than-center pulse is "right". In this simulator positive heading
        # delta means left, so invert the raw pulse ratio.
        return radians(-clamp(ratio, -1.0, 1.0) * self.max_steering_angle_deg)

    def step(self, command: ServoSteerCommand, dt_s: float) -> Pose:
        cmd = command.normalized()
        v = cmd.throttle * self.max_speed_mps
        steering = self.steering_angle_rad(cmd.pulse_us)
        omega = 0.0 if abs(v) < 1e-9 else v / self.wheel_base_m * tan(steering)
        theta_mid = self.pose.theta_rad + omega * dt_s / 2.0
        x = self.pose.x_m + v * cos(theta_mid) * dt_s
        y = self.pose.y_m + v * sin(theta_mid) * dt_s
        theta = wrap_angle_rad(self.pose.theta_rad + omega * dt_s)
        self.t_s += dt_s
        self.pose = Pose(x, y, theta)
        self.trajectory.add(TrajectorySample(self.t_s, self.pose, v, omega))
        return self.pose

    def run(self, steps: Iterable[tuple[ServoSteerCommand, float]], dt_s: float = 0.02) -> Trajectory:
        for command, duration_s in steps:
            remaining = duration_s
            while remaining > 1e-9:
                dt = min(dt_s, remaining)
                self.step(command, dt)
                remaining -= dt
        return self.trajectory
