#include "PulseOutput.h"

uint16_t pulse_output_constrain_input(uint16_t value, uint16_t min_input, uint16_t max_input) {
    if (value < min_input) {
        return min_input;
    }
    if (value > max_input) {
        return max_input;
    }
    return value;
}

uint16_t pulse_output_map_range(uint16_t value, uint16_t in_min, uint16_t in_max, uint16_t out_min, uint16_t out_max) {
    if (in_max <= in_min) {
        return out_min;
    }

    uint16_t constrained = pulse_output_constrain_input(value, in_min, in_max);
    int32_t numerator = static_cast<int32_t>(constrained - in_min) * static_cast<int32_t>(out_max - out_min);
    int32_t denominator = static_cast<int32_t>(in_max - in_min);
    return static_cast<uint16_t>(static_cast<int32_t>(out_min) + numerator / denominator);
}

uint16_t pulse_output_forward_only_us(uint16_t forward_value, uint16_t min_input, uint16_t max_input, const PulseProtocol& protocol) {
    return pulse_output_map_range(forward_value, min_input, max_input, protocol.min_us, protocol.max_us);
}

uint16_t pulse_output_bidirectional_us(uint16_t forward_value, uint16_t reverse_value, uint16_t min_input, uint16_t max_input, const PulseProtocol& protocol, uint8_t forward_deadband_pct) {
    uint16_t forward_input = pulse_output_constrain_input(forward_value, min_input, max_input);
    uint16_t reverse_input = pulse_output_constrain_input(reverse_value, min_input, max_input);
    uint32_t span = static_cast<uint32_t>(max_input - min_input);
    uint16_t forward_deadband = static_cast<uint16_t>(min_input + (span * forward_deadband_pct) / 100U);

    if ((forward_input > forward_deadband) && (reverse_input < forward_input)) {
        return pulse_output_map_range(forward_input, min_input, max_input, protocol.center_us, protocol.max_us);
    }

    return pulse_output_map_range(reverse_input, min_input, max_input, protocol.center_us, protocol.min_us);
}

uint16_t pulse_output_safe_us(const PulseProtocol& protocol, PulseEscSemantics semantics) {
    if (semantics == PULSE_ESC_BIDIRECTIONAL) {
        return protocol.center_us;
    }
    return protocol.min_us;
}

uint16_t pulse_output_duty_from_us(uint16_t pulse_us, uint16_t frame_hz, uint16_t resolution_bits) {
    if (frame_hz == 0 || resolution_bits == 0 || resolution_bits > 15) {
        return 0;
    }
    uint32_t max_pwm = (1UL << resolution_bits) - 1UL;
    uint32_t frame_period_us = 1000000UL / frame_hz;
    if (frame_period_us == 0) {
        return 0;
    }
    return static_cast<uint16_t>((static_cast<uint32_t>(pulse_us) * max_pwm) / frame_period_us);
}

PulseOutput::PulseOutput(uint8_t pwm_pin, uint8_t ledc_channel, uint8_t resolution_bits)
    : _pwm_pin(pwm_pin), _ledc_channel(ledc_channel), _resolution_bits(resolution_bits) {}

void PulseOutput::begin(const PulseProtocol& protocol) {
    configure(protocol);
    ledcAttachPin(_pwm_pin, _ledc_channel);
    ledcChangeFrequency(_ledc_channel, _protocol.frame_hz, _resolution_bits);
}

void PulseOutput::configure(const PulseProtocol& protocol) {
    _protocol = protocol;
}

void PulseOutput::setInputLimits(uint16_t min_input, uint16_t max_input) {
    _min_input = min_input;
    _max_input = max_input;
}

void PulseOutput::writePulseUs(uint16_t pulse_us) {
    _last_pulse_us = pulse_us;
    _last_duty = pulse_output_duty_from_us(pulse_us, _protocol.frame_hz, _resolution_bits);
    ledcWrite(_ledc_channel, _last_duty);
}

void PulseOutput::writeEsc(uint16_t forward_value, uint16_t reverse_value, PulseEscSemantics semantics) {
    uint16_t pulse_us = semantics == PULSE_ESC_BIDIRECTIONAL
        ? pulse_output_bidirectional_us(forward_value, reverse_value, _min_input, _max_input, _protocol)
        : pulse_output_forward_only_us(forward_value, _min_input, _max_input, _protocol);
    writePulseUs(pulse_us);
}

void PulseOutput::safeState(PulseEscSemantics semantics) {
    writePulseUs(pulse_output_safe_us(_protocol, semantics));
}
