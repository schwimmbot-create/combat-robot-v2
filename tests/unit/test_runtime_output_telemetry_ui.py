from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SKETCH=(ROOT/'main/sketch.cpp').read_text
WEB=(ROOT/'components/web_config/src/web_config.cpp').read_text
TM_H=(ROOT/'components/myrobot/include/TaskManager.h').read_text
TM_C=(ROOT/'components/myrobot/src/TaskManager.cpp').read_text
HTML=(ROOT/'docs/config-ui-mockup.html').read_text


def test_runtime_status_contract_covers_all_outputs_and_drive_truth():
    s=SKETCH()
    for token in ('main_build_runtime_output_json','\\"M1\\"','\\"M2\\"','\\"S1\\"','\\"S2\\"','speed','fwd_duty','rev_duty','frequency_hz','pulse_us','duty','logical','physical_high','esc_arm_phase','blocked_reason','left_command','right_command','throttle','steering'):
        assert token in s
    assert 'runtime_json[2048]' in WEB()
    assert '\\"runtime\\"' in WEB()


def test_blocked_reason_contract_covers_required_safety_states():
    h=TM_H(); c=TM_C()
    assert 'getOutputBlockedReason' in h
    for reason in ('disabled','low_battery','disconnect','arming','deadman','no_source','none'):
        assert f'"{reason}"' in c


def test_live_output_rows_prefer_firmware_runtime_with_local_fallback():
    html=HTML()
    assert 'state.lastStatus?.runtime?.outputs?.[id]' in html
    assert 'if (runtime)' in html
    assert html.index('if (runtime)') < html.index('liveMotorFromMock(id)', html.index('function outputStatus'))
    for label in ('BLOCKED · LOW BATTERY','BLOCKED · DISCONNECTED','WAITING · ARMING','BLOCKED · DEADMAN','BLOCKED · NO SOURCE'):
        assert label in html
    assert "for (const id of ['M1','M2','S1','S2'])" in html
    assert "cfg.display_name || outputDisplayName(id)" in html
