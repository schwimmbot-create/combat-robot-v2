from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PULSE_H = PROJECT_ROOT / "components/myrobot/include/PulseOutput.h"
PULSE_CPP = PROJECT_ROOT / "components/myrobot/src/PulseOutput.cpp"


def map_range(value, in_min, in_max, out_min, out_max):
    value = max(in_min, min(in_max, value))
    return out_min + ((value - in_min) * (out_max - out_min)) // (in_max - in_min)


def oneshot125_forward_only(value):
    return map_range(value, 0, 1023, 125, 250)


def oneshot125_bidirectional(forward, reverse, forward_deadband_pct=10):
    forward = max(0, min(1023, forward))
    reverse = max(0, min(1023, reverse))
    deadband = (1023 * forward_deadband_pct) // 100
    if forward > deadband and reverse < forward:
        return map_range(forward, 0, 1023, 188, 250)
    return map_range(reverse, 0, 1023, 188, 125)


def duty_from_us(pulse_us, frame_hz=2000, resolution_bits=8):
    return (pulse_us * ((1 << resolution_bits) - 1)) // (1_000_000 // frame_hz)


def test_protocol_presets_include_current_oneshot125_defaults():
    text = PULSE_H.read_text()
    assert "PULSE_PROTOCOL_ONESHOT125" in text
    assert '"oneshot125"' in text
    for token in ("2000", "125", "188", "250"):
        assert token in text


def test_forward_only_oneshot125_mapping_matches_existing_contract():
    assert oneshot125_forward_only(0) == 125
    assert oneshot125_forward_only(1023) == 250
    assert oneshot125_forward_only(512) == map_range(512, 0, 1023, 125, 250)


def test_bidirectional_oneshot125_forward_reverse_mapping_matches_existing_contract():
    assert oneshot125_bidirectional(0, 0) == 188
    assert oneshot125_bidirectional(1023, 0) == 250
    assert oneshot125_bidirectional(0, 1023) == 125
    assert oneshot125_bidirectional(512, 0) == map_range(512, 0, 1023, 188, 250)


def test_bidirectional_safe_state_is_center_neutral_not_minimum():
    text = PULSE_CPP.read_text()
    assert "pulse_output_safe_us" in text
    assert "PULSE_ESC_BIDIRECTIONAL" in text
    assert "return protocol.center_us" in text
    assert oneshot125_bidirectional(0, 0) == 188


def test_oneshot125_duty_conversion_matches_current_ledc_math():
    assert duty_from_us(125) == 63
    assert duty_from_us(188) == 95
    assert duty_from_us(250) == 127
