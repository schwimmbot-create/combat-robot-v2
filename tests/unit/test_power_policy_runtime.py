from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OC_H = PROJECT_ROOT / "components/output_config/include/output_config.h"
OC_C = PROJECT_ROOT / "components/output_config/src/output_config.c"
DRIVE_H = PROJECT_ROOT / "components/myrobot/include/Drive.h"
DRIVE_CPP = PROJECT_ROOT / "components/myrobot/src/Drive.cpp"
TASK = PROJECT_ROOT / "components/myrobot/src/TaskManager.cpp"


def test_output_config_exposes_channel_allowed_policy():
    header = OC_H.read_text()
    src = OC_C.read_text()
    assert "output_config_channel_allowed" in header
    assert "bool output_config_channel_allowed" in src
    assert "case OC_POWER_DISABLE" in src
    assert "cfg->purpose == OC_PURPOSE_WEAPON_ESC && battery_state == 3" in src


def test_drive_can_gate_left_and_right_motors_independently():
    header = DRIVE_H.read_text()
    src = DRIVE_CPP.read_text()
    assert "combined_direction(int joystick_x, int joystick_y, byte orientation, bool left_enabled, bool right_enabled)" in header
    assert "two_stick_drive(int left_input, int right_input, byte orientation, bool left_enabled, bool right_enabled)" in header
    assert "void Drive::stopLeft()" in src
    assert "void Drive::stopRight()" in src
    assert "if (left_enabled)" in src
    assert "if (right_enabled)" in src


def test_task_manager_uses_per_channel_power_policy_not_global_low_cutoff():
    src = TASK.read_text()
    assert "output_config_channel_allowed(OC_OUT_M1" in src
    assert "output_config_channel_allowed(OC_OUT_M2" in src
    assert "OC_OUT_WEAPON" not in src
    assert "driveLeftAllowed, driveRightAllowed" in src
    low_case = src[src.index("case BATTERY_LOW:"):src.index("default:", src.index("case BATTERY_LOW:"))]
    assert "stopAllMotors" not in low_case


def test_servo_accessory_power_policy_can_turn_led_strip_off():
    src = TASK.read_text()
    assert "output_config_channel_allowed(OC_OUT_S1" in src
    assert "output_config_channel_allowed(OC_OUT_S2" in src
    assert "ledStrip.setColor(0, 0, 0, 0);" in src
