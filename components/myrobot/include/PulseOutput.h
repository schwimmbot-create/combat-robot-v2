#ifndef PULSE_OUTPUT_H
#define PULSE_OUTPUT_H

#include <Arduino.h>

struct PulseProtocol {
    const char* name;
    uint16_t frame_hz;
    uint16_t min_us;
    uint16_t center_us;
    uint16_t max_us;
};

enum PulseEscSemantics {
    PULSE_ESC_FORWARD_ONLY = 0,
    PULSE_ESC_BIDIRECTIONAL = 1,
};

static const PulseProtocol PULSE_PROTOCOL_RC_SERVO_PWM = {
    "rc_servo_pwm",
    50,
    1000,
    1500,
    2000,
};

static const PulseProtocol PULSE_PROTOCOL_RC_ESC_PWM = {
    "rc_esc_pwm",
    50,
    1000,
    1500,
    2000,
};

static const PulseProtocol PULSE_PROTOCOL_ONESHOT125 = {
    "oneshot125",
    2000,
    125,
    188,
    250,
};

uint16_t pulse_output_constrain_input(uint16_t value, uint16_t min_input, uint16_t max_input);
uint16_t pulse_output_map_range(uint16_t value, uint16_t in_min, uint16_t in_max, uint16_t out_min, uint16_t out_max);
uint16_t pulse_output_forward_only_us(uint16_t forward_value, uint16_t min_input, uint16_t max_input, const PulseProtocol& protocol);
uint16_t pulse_output_bidirectional_us(uint16_t forward_value, uint16_t reverse_value, uint16_t min_input, uint16_t max_input, const PulseProtocol& protocol, uint8_t forward_deadband_pct = 10);
uint16_t pulse_output_safe_us(const PulseProtocol& protocol, PulseEscSemantics semantics);
uint16_t pulse_output_duty_from_us(uint16_t pulse_us, uint16_t frame_hz, uint16_t resolution_bits);

class PulseOutput {
public:
    PulseOutput(uint8_t pwm_pin, uint8_t ledc_channel, uint8_t resolution_bits = 8);

    void begin(const PulseProtocol& protocol);
    void configure(const PulseProtocol& protocol);
    void setInputLimits(uint16_t min_input = 0, uint16_t max_input = 1023);
    void writePulseUs(uint16_t pulse_us);
    void writeEsc(uint16_t forward_value, uint16_t reverse_value, PulseEscSemantics semantics);
    void safeState(PulseEscSemantics semantics);

    uint16_t lastPulseUs() const { return _last_pulse_us; }
    uint16_t lastDuty() const { return _last_duty; }
    const PulseProtocol& protocol() const { return _protocol; }

private:
    uint8_t _pwm_pin;
    uint8_t _ledc_channel;
    uint8_t _resolution_bits;
    uint16_t _min_input = 0;
    uint16_t _max_input = 1023;
    uint16_t _last_pulse_us = 0;
    uint16_t _last_duty = 0;
    PulseProtocol _protocol = PULSE_PROTOCOL_ONESHOT125;
};

#endif
