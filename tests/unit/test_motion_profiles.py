from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER = (ROOT / "components/output_config/include/output_config.h").read_text()
CONFIG = (ROOT / "components/output_config/src/output_config.c").read_text()
TASK = (ROOT / "components/myrobot/src/TaskManager.cpp").read_text()
UI = (ROOT / "docs/config-ui-mockup.html").read_text()


def test_motion_profile_round_trips_acceleration_and_deceleration():
    assert "uint16_t        deceleration_ms" in HEADER
    assert "OC_RAMP_S_CURVE" in HEADER
    assert '"acceleration_ms"' in CONFIG
    assert '"deceleration_ms"' in CONFIG
    assert '"ramp_curve"' in CONFIG
    assert '"ramp_smoothing_pct"' in CONFIG
    assert "c->ramp_ms > 10000 || c->deceleration_ms > 10000" in CONFIG


def test_motion_presets_and_custom_controls_cover_all_motion_outputs():
    for name in ("Instant", "Sport", "Medium", "Slow", "S-Curve", "Custom", "Light", "Balanced", "Strong"):
        assert f"'{name}'" in UI
    assert "cfg.purpose === 'drive' || cfg.purpose === 'servo' || cfg.purpose === 'esc'" in UI
    assert "Acceleration time (ms)" in UI
    assert "Deceleration time (ms)" in UI


def test_runtime_ramp_is_used_by_motors_servos_and_escs():
    assert "int16_t TaskManager::applyMotionRamp" in TASK
    assert "A sign reversal must decelerate through zero" in TASK
    assert "applyMotionRamp(OC_OUT_M1" in TASK
    assert "value = applyMotionRamp(id, value" in TASK
    assert "int16_t ramped = applyMotionRamp(id, target" in TASK


def test_safety_stop_resets_ramp_state_immediately():
    assert "_rampedOutput[i] = 0" in TASK
    assert "_rampUpdatedMs[i] = 0" in TASK
    assert "Disconnect and safety stops remain immediate" in UI
