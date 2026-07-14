#ifndef DRIVEMOTOR_H
#define DRIVEMOTOR_H

#include <Arduino.h>
#include "Constants.h"

struct DriveMotorIntent {
    uint16_t speed;
    byte direction;
    uint16_t fwd_duty;
    uint16_t rev_duty;
    uint16_t frequency_hz;
};


class DriveMotor{
    
    public:
        DriveMotor(byte fwd_pin, byte rev_pin,
                   byte fwd_channel, byte rev_channel,
                   bool flip_direction = false);
        void begin();
        void setPwmFrequency(uint16_t frequency_hz);
        void setSpeed(uint16_t speed, byte direction, byte orientation = RIGHTSIDE_UP);
        DriveMotorIntent getIntent() const;


    private:
        byte _fwd_pin;
        byte _rev_pin;
        byte _fwd_channel;
        byte _rev_channel;
        byte _speed = 0;
        byte _direction = STOP;
        uint16_t _fwd_duty = 0;
        uint16_t _rev_duty = 0;
        bool _flip_direction;

        uint16_t _pwm_frequency_hz = DRIVE_MOTOR_PWM_FREQ;

};


#endif