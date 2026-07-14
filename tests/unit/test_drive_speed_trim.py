from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER = (ROOT / "components/output_config/include/output_config.h").read_text()
CONFIG = (ROOT / "components/output_config/src/output_config.c").read_text()
TASK = (ROOT / "components/myrobot/src/TaskManager.cpp").read_text()
UI = (ROOT / "docs/config-ui-mockup.html").read_text()


def test_drive_speed_trim_is_persisted_and_bounded():
    assert "uint8_t left_speed_pct;" in HEADER
    assert "uint8_t right_speed_pct;" in HEADER
    assert '"left_speed_pct"' in CONFIG
    assert '"right_speed_pct"' in CONFIG
    assert "left_speed_pct > 100" in CONFIG
    assert "right_speed_pct > 100" in CONFIG


def test_drive_speed_trim_defaults_to_no_reduction():
    assert ".left_speed_pct = 100" in CONFIG
    assert ".right_speed_pct = 100" in CONFIG
    assert "left_speed_pct: 100" in UI
    assert "right_speed_pct: 100" in UI


def test_runtime_applies_side_trim_to_tank_and_arcade_commands():
    assert TASK.count("left * driveSetup->left_speed_pct") == 2
    assert TASK.count("right * driveSetup->right_speed_pct") == 2


def test_advanced_ui_exposes_straight_line_trim():
    assert "Left drive speed %" in UI
    assert "Right drive speed %" in UI
    assert "lower only the side that runs faster" in UI
