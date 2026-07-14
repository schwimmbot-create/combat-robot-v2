from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import Trajectory


@dataclass(frozen=True)
class AssertionResult:
    name: str
    passed: bool
    detail: str


class MovementAssertion(Protocol):
    def check(self, trajectory: Trajectory) -> AssertionResult: ...


@dataclass(frozen=True)
class MovesForward:
    min_distance_m: float = 0.15
    max_heading_change_deg: float = 8.0
    name: str = "moves forward"

    def check(self, trajectory: Trajectory) -> AssertionResult:
        fwd = trajectory.forward_displacement_m
        heading = abs(trajectory.heading_delta_deg)
        passed = fwd >= self.min_distance_m and heading <= self.max_heading_change_deg
        return AssertionResult(self.name, passed, f"forward={fwd:.3f}m heading_delta={trajectory.heading_delta_deg:.1f}deg")


@dataclass(frozen=True)
class MovesBackward:
    min_distance_m: float = 0.15
    max_heading_change_deg: float = 8.0
    name: str = "moves backward"

    def check(self, trajectory: Trajectory) -> AssertionResult:
        fwd = trajectory.forward_displacement_m
        heading = abs(trajectory.heading_delta_deg)
        passed = fwd <= -self.min_distance_m and heading <= self.max_heading_change_deg
        return AssertionResult(self.name, passed, f"forward={fwd:.3f}m heading_delta={trajectory.heading_delta_deg:.1f}deg")


@dataclass(frozen=True)
class TurnsLeft:
    min_heading_delta_deg: float = 15.0
    name: str = "turns left"

    def check(self, trajectory: Trajectory) -> AssertionResult:
        heading = trajectory.heading_delta_deg
        passed = heading >= self.min_heading_delta_deg
        return AssertionResult(self.name, passed, f"heading_delta={heading:.1f}deg")


@dataclass(frozen=True)
class TurnsRight:
    min_heading_delta_deg: float = 15.0
    name: str = "turns right"

    def check(self, trajectory: Trajectory) -> AssertionResult:
        heading = trajectory.heading_delta_deg
        passed = heading <= -self.min_heading_delta_deg
        return AssertionResult(self.name, passed, f"heading_delta={heading:.1f}deg")


@dataclass(frozen=True)
class ArcsLeft:
    min_distance_m: float = 0.10
    min_heading_delta_deg: float = 8.0
    name: str = "arcs left"

    def check(self, trajectory: Trajectory) -> AssertionResult:
        fwd = abs(trajectory.forward_displacement_m)
        heading = trajectory.heading_delta_deg
        passed = fwd >= self.min_distance_m and heading >= self.min_heading_delta_deg
        return AssertionResult(self.name, passed, f"abs_forward={fwd:.3f}m heading_delta={heading:.1f}deg")


@dataclass(frozen=True)
class ArcsRight:
    min_distance_m: float = 0.10
    min_heading_delta_deg: float = 8.0
    name: str = "arcs right"

    def check(self, trajectory: Trajectory) -> AssertionResult:
        fwd = abs(trajectory.forward_displacement_m)
        heading = trajectory.heading_delta_deg
        passed = fwd >= self.min_distance_m and heading <= -self.min_heading_delta_deg
        return AssertionResult(self.name, passed, f"abs_forward={fwd:.3f}m heading_delta={heading:.1f}deg")


@dataclass(frozen=True)
class EndsStopped:
    max_final_speed_mps: float = 0.02
    name: str = "ends stopped"

    def check(self, trajectory: Trajectory) -> AssertionResult:
        speed = trajectory.final_speed_mps
        passed = speed <= self.max_final_speed_mps
        return AssertionResult(self.name, passed, f"final_speed={speed:.3f}m/s")


@dataclass(frozen=True)
class HoldsStill:
    max_distance_m: float = 0.02
    max_heading_delta_deg: float = 2.0
    name: str = "holds still"

    def check(self, trajectory: Trajectory) -> AssertionResult:
        dist = trajectory.displacement_m
        heading = abs(trajectory.heading_delta_deg)
        passed = dist <= self.max_distance_m and heading <= self.max_heading_delta_deg
        return AssertionResult(self.name, passed, f"displacement={dist:.3f}m heading_delta={trajectory.heading_delta_deg:.1f}deg")


def check_all(trajectory: Trajectory, assertions: list[MovementAssertion]) -> list[AssertionResult]:
    return [assertion.check(trajectory) for assertion in assertions]
