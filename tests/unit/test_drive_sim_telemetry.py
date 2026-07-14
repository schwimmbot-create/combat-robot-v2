from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from drive_sim.telemetry import differential_command_from_status, servo_steer_command_from_status


@dataclass
class Status:
    m1_speed: int = 0
    m1_dir: str = "stop"
    m2_speed: int = 0
    m2_dir: str = "stop"
    drive_left: int = 0
    drive_right: int = 0
    s1_pulse_us: int = 1500
    s2_pulse_us: int = 1500


@dataclass
class MotorOnlyStatus:
    m1_speed: int = 0
    m1_dir: str = "stop"
    m2_speed: int = 0
    m2_dir: str = "stop"


def test_differential_command_prefers_semantic_drive_left_right():
    cmd = differential_command_from_status(Status(drive_left=-255, drive_right=511, m1_speed=255, m1_dir="reverse", m2_speed=128, m2_dir="forward"))
    assert -0.51 < cmd.left < -0.49
    assert cmd.right == 1.0


def test_differential_command_can_fallback_to_motor_intent():
    cmd = differential_command_from_status(MotorOnlyStatus(m1_speed=255, m1_dir="reverse", m2_speed=128, m2_dir="forward"))
    assert cmd.left == 1.0
    assert -0.51 < cmd.right < -0.49


def test_servo_steer_command_uses_semantic_drive_and_s1_pulse():
    cmd = servo_steer_command_from_status(Status(drive_left=255, drive_right=0, m1_speed=128, m1_dir="reverse", s1_pulse_us=1000))
    assert 0.49 < cmd.throttle < 0.51
    assert cmd.pulse_us == 1000
