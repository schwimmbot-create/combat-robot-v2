from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER = (ROOT / "components/output_config/include/output_config.h").read_text()
CONFIG = (ROOT / "components/output_config/src/output_config.c").read_text()
TASK_H = (ROOT / "components/myrobot/include/TaskManager.h").read_text()
TASK = (ROOT / "components/myrobot/src/TaskManager.cpp").read_text()
UI = (ROOT / "docs/config-ui-mockup.html").read_text()


def test_precision_latching_round_trips_and_defaults_to_while_pressed():
    assert "bool precision_latching" in HEADER
    assert ".precision_latching = false" in CONFIG
    assert '"precision_latching"' in CONFIG
    assert 'parse_bare_bool_value(&p, &next.precision_latching)' in CONFIG


def test_precision_latching_toggles_only_on_rising_edge_and_resets_on_stop():
    assert "_precisionLatched" in TASK_H
    assert "pressed && !_precisionPrevPressed" in TASK
    assert "_precisionLatched = !_precisionLatched" in TASK
    assert "_precisionLatched = false" in TASK
    assert "precisionModifierActive(setup, cs)" in TASK


def test_ui_exposes_precision_latching_and_drive_motor_inversion_checkboxes():
    assert "Latch precision control (press to toggle)" in UI
    assert "precision_latching = e.target.checked" in UI
    assert "Invert ${o.id} motor direction" in UI
    assert "cfg.direction = e.target.checked ? 'reversed' : 'normal'" in UI


def test_drive_paths_apply_per_motor_direction():
    assert TASK.count("leftCfg->direction == OC_DIR_REVERSED") >= 2
    assert TASK.count("rightCfg->direction == OC_DIR_REVERSED") >= 2
    assert "motorCfg->direction == OC_DIR_REVERSED" in TASK
