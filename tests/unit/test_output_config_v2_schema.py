from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OC_H = PROJECT_ROOT / "components/output_config/include/output_config.h"
OC_C = PROJECT_ROOT / "components/output_config/src/output_config.c"


def test_output_config_v2_enums_exist():
    header = OC_H.read_text()
    for token in (
        "OC_PURPOSE_DRIVE",
        "OC_PURPOSE_SERVO",
        "OC_PURPOSE_DIGITAL_INPUT",
        "OC_PROTO_RC_SERVO_PWM",
        "OC_PROTO_RC_SERVO_PPM",
        "OC_PROTO_RC_ESC_PWM",
        "OC_PROTO_ONESHOT125",
        "OC_PROTO_ONESHOT42",
        "OC_PROTO_MULTISHOT",
        "OC_PROTO_RC_SERVO_PWM_100",
        "OC_PROTO_RC_SERVO_PWM_200",
        "OC_PROTO_RC_SERVO_PWM_333",
        "OC_PROTO_RC_ESC_PWM_100",
        "OC_PROTO_RC_ESC_PWM_250",
        "OC_PROTO_RC_ESC_PWM_333",
        "OC_PROTO_RC_ESC_PWM_490",
        "OC_PROTO_ONESHOT",
        "OC_SEM_ESC_BIDIRECTIONAL",
        "OC_POWER_DISABLE",
        "OC_WEAPON_ARMING_AND_DEADMAN",
        "OC_ESC_ARM_MANUAL",
        "OC_ESC_ARM_BOOT",
        "OC_ESC_ARM_HOLD_SOURCE",
        "OC_DIGITAL_MODE_DIRECT",
        "OC_DIGITAL_MODE_ANALOG_ABOVE",
        "OC_DIGITAL_MODE_ANALOG_BELOW",
        "OC_DIGITAL_PRESET_TRIGGER_HALF",
        "OC_DIGITAL_PRESET_CUSTOM",
        "OC_DRIVE_LAYOUT_DIFFERENTIAL",
        "OC_DRIVE_LAYOUT_SERVO_STEERING",
        "OC_DRIVE_METHOD_TANK",
        "OC_DRIVE_METHOD_ARCADE",
        "OC_DRIVE_AXIS_RT_MINUS_LT",
        "OC_DRIVE_AXIS_DPAD_X",
        "oc_drive_setup_t",
    ):
        assert token in header


def test_output_config_v2_defaults_preserve_current_roles():
    src = OC_C.read_text()
    assert '.display_name = "Motor 1", .purpose = OC_PURPOSE_DRIVE, .protocol = OC_PROTO_NONE' in src
    assert '.display_name = "Motor 2", .purpose = OC_PURPOSE_DRIVE, .protocol = OC_PROTO_NONE' in src
    assert 'OC_OUT_WEAPON' not in src
    assert '"Weapon",' not in src
    assert '.display_name = "Servo 1", .purpose = OC_PURPOSE_SERVO, .protocol = OC_PROTO_RC_SERVO_PWM' in src
    assert '.display_name = "Servo 2", .purpose = OC_PURPOSE_SERVO, .protocol = OC_PROTO_RC_SERVO_PWM' in src


def test_output_config_v2_json_exposes_new_fields():
    src = OC_C.read_text()
    for literal in (
        '\\"purpose\\"',
        '\\"protocol\\"',
        '\\"semantics\\"',
        '\\"pulse\\"',
        '\\"min_us\\"',
        '\\"center_us\\"',
        '\\"max_us\\"',
        '\\"frame_hz\\"',
        '\\"safety\\"',
        '\\"weapon_mode\\"',
        '\\"deadman_source\\"',
        '\\"power\\"',
        '\\"LOW\\"',
        '\\"digital_mode\\"',
        '\\"digital_preset\\"',
        '\\"digital_on_threshold\\"',
        '\\"digital_off_threshold\\"',
        '\\"digital_custom_pct\\"',
    ):
        assert literal in src


def test_output_config_accepts_expanded_pulse_protocols_and_rejects_weapon_hold_last():
    src = OC_C.read_text()
    for token in (
        "rc_servo_pwm_100",
        "rc_servo_pwm_200",
        "rc_servo_pwm_333",
        "rc_esc_pwm_100",
        "rc_esc_pwm_250",
        "rc_esc_pwm_333",
        "rc_esc_pwm_490",
        "oneshot",
        "oneshot42",
        "multishot",
    ):
        assert token in src
    assert "protocol == OC_PROTO_ONESHOT42 || protocol == OC_PROTO_MULTISHOT" not in src
    assert "c->weapon_safety && c->failsafe == OC_FAILSAFE_HOLD_LAST" in src
    assert "purpose_protocol_is_valid" in src


def test_output_config_patch_accepts_v2_editable_fields():
    src = OC_C.read_text()
    for field in (
        "display_name",
        "purpose",
        "protocol",
        "semantics",
        "min_pulse_us",
        "center_pulse_us",
        "max_pulse_us",
        "frame_hz",
        "weapon_safety",
        "failsafe",
        "weapon_mode",
        "arming_source",
        "deadman_source",
        "power_good",
        "power_warn",
        "power_low",
        "digital_mode",
        "digital_preset",
        "digital_on_threshold",
        "digital_off_threshold",
        "digital_custom_pct",
        "esc_arm_mode",
        "esc_arm_source",
        "esc_arm_hold_ms",
        "esc_arm_low_us",
        "esc_arm_high_us",
        "esc_arm_low_ms",
        "esc_arm_high_ms",
        "esc_arm_final_low_ms",
    ):
        assert f'"{field}"' in src


def test_digital_threshold_validation_contract():
    src = OC_C.read_text()
    assert "digital_thresholds_are_sane" in src
    assert "digital_mode == OC_DIGITAL_MODE_ANALOG_ABOVE" in src
    assert "digital_on_threshold > c->digital_off_threshold" in src
    assert "digital_mode == OC_DIGITAL_MODE_ANALOG_BELOW" in src
    assert "digital_on_threshold < c->digital_off_threshold" in src
    assert "digital_custom_pct > 100" in src
    assert "d < -1024 || d > 1024" in src


def test_current_output_contract_has_four_channels():
    header = OC_H.read_text()
    src = OC_C.read_text()
    assert "OC_OUT__COUNT  = 4" in header
    assert "OC_OUT_WEAPON" not in header
    assert '"M1", "M2", "S1", "S2"' in src
    assert 'strcmp(key, "Weapon") == 0' in src


def test_esc_arming_validation_contract():
    src = OC_C.read_text()
    header = OC_H.read_text()
    assert "oc_esc_arm_mode_t" in header
    assert "kEscArmModeNames" in src
    assert "esc_arm_low_us >= c->esc_arm_high_us" in src
    assert "esc_arm_hold_ms > 10000" in src
    assert "esc_arm_mode_from_str" in src


def test_composable_drive_setup_api_and_legacy_mapping():
    src = OC_C.read_text()
    for token in (
        "drive_setup_for_legacy_mode",
        "OC_NVS_KEY_DRIVE_SETUP",
        "apply_drive_patch",
        "RT_MINUS_LT",
        "DPAD_Y",
        "precision_scale_pct",
        "output_config_get_drive_setup",
    ):
        assert token in src


def test_manual_motor_momentary_latching_reject_analog_sources():
    src = OC_C.read_text()
    html = (PROJECT_ROOT / "docs" / "config-ui-mockup.html").read_text()
    assert "source_is_digital_only" in src
    assert "OC_MOTOR_MODE_MOMENTARY || c->motor_mode == OC_MOTOR_MODE_LATCHING" in src
    assert "!source_is_digital_only(c->primary)" in src
    assert "MANUAL_MOTOR_DIGITAL_SOURCES" in html
    assert "Momentary and latching controls use digital sources only" in html
