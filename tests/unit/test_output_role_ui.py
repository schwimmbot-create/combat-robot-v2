from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HTML = PROJECT_ROOT / "docs/config-ui-mockup.html"
GEN = PROJECT_ROOT / "components/web_config/src/web_index_gen.h"


def test_four_channel_ui_has_no_dedicated_weapon_output():
    html = HTML.read_text()
    assert "M1/M2 are drive motors only" in html
    assert "there is no dedicated Weapon output" in html
    assert "id: 'Weapon'" not in html
    assert "state.outputs.Weapon" not in html
    assert "['M1','M2','Weapon','S1','S2']" not in html


def test_s1_s2_role_ui_exposes_weapon_controls_not_weapon_card():
    html = HTML.read_text()
    for token in (
        "function renderEscSafetyControls",
        "ESC safety controls on",
        "Use Safety-critical weapon role",
        "weapon_mode",
        "arming_source",
        "deadman_source",
        "ramp_ms",
        "Safety-critical weapon role",
        "rc_servo_ppm",
        "Advanced: pulse calibration",
        "applyPulseDefaults",
    ):
        assert token in html


def test_aux_role_ui_exposes_pulse_digital_input_and_pwm_sections():
    html = HTML.read_text()
    for token in (
        "function renderPulseControls",
        "Advanced: pulse calibration",
        "Min pulse (µs)",
        "Center pulse (µs)",
        "Max pulse (µs)",
        "Frame rate (Hz)",
        "function renderDigitalInputControls",
        "Digital input",
        "function renderPwmAccessoryControls",
        "PWM accessory",
        "pwm_frequency_hz: cfg.pwm?.frequency_hz",
        "pwm_duty_pct: cfg.pwm?.duty_pct",
    ):
        assert token in html


def test_upload_rejects_obsolete_weapon_configs():
    html = HTML.read_text()
    assert "data.outputs_patch.Weapon !== undefined" in html
    assert "data.outputs.Weapon !== undefined" in html
    assert "data.Weapon !== undefined" in html
    assert "obsolete Weapon output is not supported" in html


def test_embedded_header_has_role_ui():
    gen = GEN.read_text()
    assert "ESC safety controls on" in gen
    assert "Advanced: pulse calibration" in gen
    assert "PWM accessory" in gen


def test_no_weapon_esc_purpose_option():
    html = HTML.read_text()
    assert "['weapon_esc'" not in html
    assert "Weapon ESC" not in html
    assert "weapon_esc" not in html


def test_protocol_changes_reset_pulse_defaults_and_servo_ppm_available():
    html = HTML.read_text()
    for token in (
        "rc_servo_ppm",
        "RC Servo PPM 50 Hz",
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
        assert token in html
    assert "applyPulseDefaults(state.outputs[o.id], e.target.value)" in html
    assert "oneshot125:" in html and "min_us: 125" in html
    assert "oneshot42:" in html and "min_us: 42" in html
    assert "multishot:" in html and "min_us: 5" in html
    assert "rc_servo_pwm:" in html and "frame_hz: 50" in html
    assert "<details" not in html  # generated via DOM helper, not literal markup
    assert "Advanced: pulse calibration" in html


def test_esc_arming_ui():
    html = HTML.read_text()
    for token in (
        "function renderEscArmingControls",
        "Manual arming — user performs ESC sequence",
        "Auto-arm at boot",
        "Auto-arm after holding a button/source",
        "Arming signal sequence",
        "esc_arm_mode: cfg.esc_arm?.mode",
        "esc_arm_final_low_ms",
    ):
        assert token in html
