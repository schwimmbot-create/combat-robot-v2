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
    assert "pulse.writeEsc((uint16_t)max(0, (int)ramped * 2)" in src


def test_weapon_role_safety_is_attached_to_s1_s2_runtime():
    src = TASK_CPP.read_text()
    assert "bool TaskManager::weaponRoleArmed" in src
    assert "OC_WEAPON_DEADMAN_ONLY" in src
    assert "OC_WEAPON_ARMING_AND_DEADMAN" in src
    assert "cfg->arming_source" in src
    assert "cfg->deadman_source" in src
    assert "output_config_channel_allowed(id, batteryState)" in src
    assert "pulse.safeState(semantics)" in src


def test_esc_arming_state_machine_runtime():
    header = TASK_H.read_text()
    src = TASK_CPP.read_text()
    assert "EscArmState" in header
    assert "bool TaskManager::updateEscArming" in src
    assert "OC_ESC_ARM_MANUAL" in src
    assert "OC_ESC_ARM_BOOT" in src
    assert "OC_ESC_ARM_HOLD_SOURCE" in src
    assert "cfg->esc_arm_low_us" in src
    assert "cfg->esc_arm_high_us" in src
    assert "pulse.writePulseUs(cfg->esc_arm_high_us)" in src
    assert "ESC_ARM_PHASE_HIGH" in src
    assert "getEscArmPhaseName" in header
    assert "getAuxPulseUs" in header
    assert "if (!escArmed)" in src


def test_expanded_pulse_protocol_runtime_mapping():
    src = TASK_CPP.read_text()
    pulse_h = (PROJECT_ROOT / "components/myrobot/include/PulseOutput.h").read_text()
    for token in (
        "PULSE_PROTOCOL_RC_SERVO_PWM_100",
        "PULSE_PROTOCOL_RC_SERVO_PWM_200",
        "PULSE_PROTOCOL_RC_SERVO_PWM_333",
        "PULSE_PROTOCOL_RC_ESC_PWM_100",
        "PULSE_PROTOCOL_RC_ESC_PWM_250",
        "PULSE_PROTOCOL_RC_ESC_PWM_333",
        "PULSE_PROTOCOL_RC_ESC_PWM_490",
        "PULSE_PROTOCOL_ONESHOT",
        "PULSE_PROTOCOL_ONESHOT125",
        "PULSE_PROTOCOL_ONESHOT42",
        "PULSE_PROTOCOL_MULTISHOT",
    ):
        assert token in pulse_h
        assert token in src
    assert "OC_PROTO_MULTISHOT" in src
    assert "frame_hz" in pulse_h


def test_composable_drive_runtime_and_servo_steering():
    header = TASK_H.read_text()
    src = TASK_CPP.read_text()
    drive_h = (PROJECT_ROOT / "components/myrobot/include/Drive.h").read_text()
    drive_cpp = (PROJECT_ROOT / "components/myrobot/src/Drive.cpp").read_text()
    for token in (
        "readDriveAxis",
        "OC_DRIVE_AXIS_RT_MINUS_LT",
        "OC_DRIVE_AXIS_DPAD_Y",
        "applyDriveModifiersToThrottle",
        "applyDriveModifiersToSteering",
        "outputReservedForDriveSteering",
        "updateSteeringServo",
        "output_config_get_drive_setup",
        "OC_DRIVE_LAYOUT_SERVO_STEERING",
        "getDriveThrottle",
    ):
        assert token in header or token in src
    assert "single_motor_drive" in drive_h
    assert "void Drive::single_motor_drive" in drive_cpp
    assert "drive={layout:%s,method:%s,throttle_axis:%s,steering_axis:%s,throttle:%d,steering:%d,left:%d,right:%d}" in (PROJECT_ROOT / "main/sketch.cpp").read_text()


def test_loop_feeds_stick_x_axes_to_task_manager():
    main = (PROJECT_ROOT / "main/sketch.cpp").read_text()
    assert "controllerState.leftStickX    = gs.leftStickX" in main
    assert "controllerState.rightStickX   = gs.rightStickX" in main
    assert "controllerState.leftStickX    = 0" in main
    assert "controllerState.rightStickX   = 0" in main
