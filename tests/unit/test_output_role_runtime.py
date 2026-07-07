from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASK_H = PROJECT_ROOT / "components/myrobot/include/TaskManager.h"
TASK_CPP = PROJECT_ROOT / "components/myrobot/src/TaskManager.cpp"
CONSTANTS = PROJECT_ROOT / "components/myrobot/include/Constants.h"


def test_task_manager_has_no_fixed_weapon_or_drum_path():
    header = TASK_H.read_text()
    src = TASK_CPP.read_text()
    assert "Drum drum" not in header
    assert "#include \"Drum.h\"" not in header
    assert "drum.begin" not in src
    assert "drum.setSpeed" not in src
    assert "OC_OUT_WEAPON" not in src


def test_s1_s2_use_pulse_output_for_role_routing():
    header = TASK_H.read_text()
    src = TASK_CPP.read_text()
    constants = CONSTANTS.read_text()
    assert "SERVO1_PWM_CHANNEL 4" in constants
    assert "SERVO2_PWM_CHANNEL 5" in constants
    assert "AUX_PWM_RESOLUTION 14" in constants
    assert "AUX_PWM_RESOLUTION" in src
    assert "PulseOutput _s1Pulse" in header
    assert "PulseOutput _s2Pulse" in header
    assert "updateAuxOutput(OC_OUT_S1, PIN_SERVO1, self->_s1Pulse" in src
    assert "updateAuxOutput(OC_OUT_S2, PIN_SERVO2, self->_s2Pulse" in src
    assert "void TaskManager::updatePulseOutput" in src
    assert "!cfg->weapon_safety" in src
    assert "pulse.writeEsc(forward, reverse, semantics)" in src


def test_weapon_role_safety_is_attached_to_s1_s2_runtime():
    src = TASK_CPP.read_text()
    assert "bool TaskManager::weaponRoleArmed" in src
    assert "OC_WEAPON_DEADMAN_ONLY" in src
    assert "OC_WEAPON_ARMING_AND_DEADMAN" in src
    assert "cfg->arming_source" in src
    assert "cfg->deadman_source" in src
    assert "output_config_channel_allowed(id, batteryState)" in src
    assert "pulse.safeState(semantics)" in src
