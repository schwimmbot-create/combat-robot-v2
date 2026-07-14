from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HTML = PROJECT_ROOT / "docs/config-ui-mockup.html"
OC_H = PROJECT_ROOT / "components/output_config/include/output_config.h"
OC_C = PROJECT_ROOT / "components/output_config/src/output_config.c"
TM_CPP = PROJECT_ROOT / "components/myrobot/src/TaskManager.cpp"
BUTTONS_CPP = PROJECT_ROOT / "components/myrobot/src/Buttons.cpp"
CONSTANTS_H = PROJECT_ROOT / "components/myrobot/include/Constants.h"


def test_sw1_actions_are_firmware_backed_and_persisted():
    h = OC_H.read_text()
    c = OC_C.read_text()
    tm = TM_CPP.read_text()
    for token in (
        "oc_sw1_action_t",
        "oc_sw1_config_t",
        "output_config_get_sw1_config",
        "output_config_set_sw1_config",
        "OC_NVS_KEY_SW1_CONFIG",
        "apply_sw1_patch",
        "sw1",
        "output_config_sw1_action_name",
    ):
        assert token in h + c
    for token in (
        "handleSw1Action",
        "OC_SW1_ACTION_PAIRING",
        "OC_SW1_ACTION_CLEAR_PAIR",
        "OC_SW1_ACTION_CANCEL_PAIRING",
        "OC_SW1_ACTION_RESET_OUTPUTS",
        "OC_SW1_ACTION_BATTERY_STATUS",
        "buttons.setHoldTimeMs",
    ):
        assert token in tm


def test_button_driver_supports_double_press_and_configurable_hold_time():
    constants = CONSTANTS_H.read_text()
    buttons = BUTTONS_CPP.read_text()
    assert "BUTTON_DOUBLE" in constants
    assert "DOUBLE_PRESS_TIME" in constants
    assert "setHoldTimeMs" in buttons
    assert "shortPending" in buttons
    assert "BUTTON_DOUBLE" in buttons
    assert "pdMS_TO_TICKS(holdTimeMs)" in buttons


def test_disconnect_failsafe_override_is_firmware_backed():
    h = OC_H.read_text()
    c = OC_C.read_text()
    tm = TM_CPP.read_text()
    for token in (
        "OC_NVS_KEY_DISCONNECT_FAILSAFE",
        "output_config_get_disconnect_failsafe_hold_last",
        "output_config_set_disconnect_failsafe_hold_last",
        "\"disconnect_failsafe\"",
        "hold_last",
        "safe_stop",
    ):
        assert token in h + c
    assert "!output_config_get_disconnect_failsafe_hold_last()" in tm
    assert "stopAllMotors();" in tm


def test_sw1_and_disconnect_failsafe_are_emitted_by_config_get():
    c = OC_C.read_text()
    start = c.index("int output_config_to_json")
    end = c.index("int output_config_sources_to_json", start)
    serializer = c[start:end]
    assert '\\"disconnect_failsafe\\"' in serializer
    assert 's_disconnect_failsafe_hold_last ? "hold_last" : "safe_stop"' in serializer
    assert '\\"sw1\\"' in serializer
    for member in ("short_action", "double_action", "hold_action", "hold_ms"):
        assert f'\\"{member}\\"' in serializer


def test_html_exposes_sw1_and_disconnect_controls_without_bench_language():
    html = HTML.read_text()
    for token in (
        "Disconnect Failsafe Override",
        "DANGER: hold-last keeps the last sent controller value active",
        "btn-disconnect-failsafe-save",
        "normalizeSw1Config",
        "Firmware-backed physical mode button actions",
        "hold_action",
        "hold_ms",
        "sw1: normalizeSw1Config(state.sw1)",
        "disconnect_failsafe: state.disconnect_failsafe",
    ):
        assert token in html
    for forbidden in ("bench_e2e", "drive_sim", "artifacts/drive-sim"):
        assert forbidden not in html


def test_power_cards_preserve_expanded_state_and_titles_left_aligned():
    html = HTML.read_text()
    for token in (
        "const powerOpenCards = new Set()",
        "rememberPowerOpenState",
        "powerOpenCards.has(id)",
        "details.addEventListener('toggle'",
        "const rerender = () => { rememberPowerOpenState(); renderPowerBehavior(); }",
        "text-align: left",
        ".output-title { justify-content: flex-start; text-align: left; }",
    ):
        assert token in html
