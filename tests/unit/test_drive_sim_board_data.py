from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from drive_sim.board_data import load_board_data, supported_board_revs
from drive_sim.scenarios import board_scenarios, run_board_scenarios


def test_board_data_loads_v2_and_v3_from_actual_board_config():
    assert supported_board_revs() == [2, 3]
    v2 = load_board_data(2)
    v3 = load_board_data(3)
    assert v2.name == "Generic Robot Controller v2"
    assert v2.num_drive_motors == 2
    assert v2.chassis_kind == "differential"
    assert not v2.has_spare_header
    assert v3.name == "Generic Robot Controller v3"
    assert v3.num_drive_motors == 4
    assert v3.chassis_kind == "four_wheel_skid"
    assert v3.has_spare_header


def test_board_scenarios_use_board_drive_motor_count():
    v2 = load_board_data(2)
    v3 = load_board_data(3)
    v2_scenarios = board_scenarios(v2)
    v3_scenarios = board_scenarios(v3)
    assert any(s.kind == "differential" for s in v2_scenarios)
    assert not any(s.kind == "four_wheel_skid" for s in v2_scenarios)
    assert any(s.kind == "four_wheel_skid" for s in v3_scenarios)
    assert all(result.passed for result in run_board_scenarios(v2))
    assert all(result.passed for result in run_board_scenarios(v3))
