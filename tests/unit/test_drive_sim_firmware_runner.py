from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from drive_sim.assertions import ArcsLeft, EndsStopped, MovesForward
from drive_sim.board_data import load_board_data
from drive_sim.firmware_runner import TimedStatus, simulate_status_samples


@dataclass
class Status:
    m1_speed: int = 0
    m1_dir: str = "stop"
    m2_speed: int = 0
    m2_dir: str = "stop"
    s1_pulse_us: int = 1500
    s2_pulse_us: int = 1500


def test_simulate_differential_firmware_samples_forward_then_stop():
    board = load_board_data(2)
    samples = [
        TimedStatus(0.0, Status(m1_speed=180, m1_dir="reverse", m2_speed=180, m2_dir="reverse")),
        TimedStatus(1.0, Status(m1_speed=0, m1_dir="stop", m2_speed=0, m2_dir="stop")),
        TimedStatus(1.2, Status(m1_speed=0, m1_dir="stop", m2_speed=0, m2_dir="stop")),
    ]
    result = simulate_status_samples(
        name="synthetic_forward",
        kind="differential",
        samples=samples,
        assertions=[MovesForward(), EndsStopped()],
        board=board,
    )
    assert result.passed


def test_simulate_servo_steer_firmware_samples_left_arc():
    board = load_board_data(2)
    samples = [
        TimedStatus(0.0, Status(m1_speed=170, m1_dir="reverse", s1_pulse_us=1000)),
        TimedStatus(0.8, Status(m1_speed=0, m1_dir="stop", s1_pulse_us=1500)),
        TimedStatus(1.0, Status(m1_speed=0, m1_dir="stop", s1_pulse_us=1500)),
    ]
    result = simulate_status_samples(
        name="synthetic_servo_left",
        kind="servo_steer",
        samples=samples,
        assertions=[ArcsLeft(), EndsStopped()],
        board=board,
    )
    assert result.passed
