from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BENCH = PROJECT_ROOT / "tools/bench_e2e.py"


def test_bench_status_parser_includes_digital_outputs():
    src = BENCH.read_text()
    assert "s1_logical" in src
    assert "s1_physical_high" in src
    assert "outputs=\\{S1:" in src
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
        "configure_s2_esc_arming",
        "esc_arm_mode\": \"hold_source\"",
        "esc_arm_low_us\": 125",
        "PASS API accepts S2 ESC hold-to-arm sequence config",
        "restore_s2_servo",
    ):
        assert token in src
