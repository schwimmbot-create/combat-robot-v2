#ifndef DRIVEMOTOR_H
#define DRIVEMOTOR_H

#include <Arduino.h>
#include "Constants.h"


class DriveMotor{
    
    public:
        DriveMotor(byte fwd_pin, byte rev_pin,
                   byte fwd_channel, byte rev_channel,
                   bool flip_direction = false);
        void begin();
        void setPwmFrequency(uint16_t frequency_hz);
        void setSpeed(uint16_t speed, byte direction, byte orientation = RIGHTSIDE_UP);


    private:
        byte _fwd_pin;
        byte _rev_pin;
        byte _fwd_channel;
        byte _rev_channel;
        byte _speed;
        byte _direction;
        bool _flip_direction;

        uint16_t _pwm_frequency_hz = DRIVE_MOTOR_PWM_FREQ;

};


#endif