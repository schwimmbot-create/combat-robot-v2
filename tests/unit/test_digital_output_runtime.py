from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TM_H = PROJECT_ROOT / "components/myrobot/include/TaskManager.h"
TM_CPP = PROJECT_ROOT / "components/myrobot/src/TaskManager.cpp"
SKETCH = PROJECT_ROOT / "main/sketch.cpp"
WEB = PROJECT_ROOT / "components/web_config/src/web_config.cpp"


def test_taskmanager_has_digital_output_evaluator_and_gpio_driver():
    header = TM_H.read_text()
    src = TM_CPP.read_text()
    assert "evaluateDigitalOutput" in header
    assert "readConfigSource" in header
    assert "updateDigitalOutput" in header
    assert "OC_DIGITAL_MODE_DIRECT" in src
    assert "OC_DIGITAL_MODE_ANALOG_ABOVE" in src
    assert "OC_DIGITAL_MODE_ANALOG_BELOW" in src
    assert "digitalWrite(pin, physicalHigh ? HIGH : LOW)" in src
    assert "output_config_channel_allowed(id, batteryState)" in src


def test_taskmanager_maps_buttons_dpad_triggers_and_sticks():
    src = TM_CPP.read_text()
    for token in (
        "case OC_SRC_BTN_A",
        "case OC_SRC_BTN_START",
        "case OC_SRC_DPAD_UP",
        "case OC_SRC_DPAD_RIGHT",
        "case OC_SRC_RT",
        "case OC_SRC_LT",
        "case OC_SRC_LY",
        "case OC_SRC_RX",
    ):
        assert token in src


def test_status_surfaces_s1_s2_logical_and_physical_states():
    sketch = SKETCH.read_text()
    web = WEB.read_text()
    assert "main_get_digital_output_logical" in sketch
    assert "main_get_digital_output_physical_high" in sketch
    assert "outputs={S1:{logical:%d,physical_high:%d,pulse_us:%u,duty:%u,arm:%s},S2:{logical:%d,physical_high:%d,pulse_us:%u,duty:%u,arm:%s}}" in sketch
    assert '\\"outputs\\"' in web
    assert '\\"physical_high\\"' in web
    assert "main_get_digital_output_logical(OC_OUT_S1)" in web
    assert "main_get_digital_output_physical_high(OC_OUT_S2)" in web
