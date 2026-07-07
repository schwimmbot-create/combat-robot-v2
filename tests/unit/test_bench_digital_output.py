from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BENCH = PROJECT_ROOT / "tools/bench_e2e.py"


def test_bench_status_parser_includes_digital_outputs():
    src = BENCH.read_text()
    assert "s1_logical" in src
    assert "s1_physical_high" in src
    assert "s1_pulse_us" in src
    assert "s1_arm" in src
    assert "s2_pulse_us" in src
    assert "s2_arm" in src
    assert "outputs=\\{S1:" in src
    assert "pulse_us:" in src
    assert "arm:" in src
    assert "S2:" in src


def test_bench_exercises_button_inversion_and_thresholds():
    src = BENCH.read_text()
    for token in (
        "configure_s1_digital",
        "primary=\"A\", active_high=True",
        "S1 digital BTN_A pressed -> HIGH",
        "primary=\"A\", active_high=False",
        "S1 inverted BTN_A pressed -> physical LOW",
        "primary=\"RT\"",
        "digital_mode=\"analog_above\"",
        "on=600, off=500",
        "S1 RT hysteresis holds on",
        "restore_s1_servo",
        "obsolete Weapon config patch unexpectedly succeeded",
        "PASS API rejects obsolete top-level Weapon config",
        "verify_s2_esc_protocol_presets",
        "ESC_PROTOCOL_PRESETS",
        "rc_esc_pwm_490",
        "oneshot42",
        "multishot",
        "PASS S2 ESC expanded protocol presets",
        "configure_s2_esc_arming",
        "esc_arm_mode\": \"hold_source\"",
        "esc_arm_low_us\": 125",
        "PASS API accepts S2 ESC hold-to-arm sequence config",
        "verify_s2_hold_to_arm_with_usb_dongle",
        "S2 ESC arming sequence high pulse",
        "s.s2_arm == \"high\" and s.s2_pulse_us == 250",
        "S2 ESC throttle accepted after arming",
        "PASS S2 ESC hold-to-arm sequence via USB dongle",
        "restore_s2_servo",
    ):
        assert token in src
