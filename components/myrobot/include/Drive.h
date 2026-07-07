#ifndef DRIVE_H
#define DRIVE_H

#include <Arduino.h>
#include "Constants.h"
#include "DriveMotor.h"

class Drive{
    public:
        Drive();
        void begin();
        void setMotorPwmFrequency(bool left_motor, uint16_t frequency_hz);
        void setForwardInputLimits(int minInput = -512, int maxInput = 511);
        void setLateralInputLimits(int minInput = -512, int maxInput = 511);
        void setPwmResolution(int resolution = 8);
        void combined_direction(int joystick_x, int joystick_y, byte orientation);
        void combined_direction(int joystick_x, int joystick_y, byte orientation, bool left_enabled, bool right_enabled);
        void two_stick_drive(int left_input, int right_input, byte orientation);
        void two_stick_drive(int left_input, int right_input, byte orientation, bool left_enabled, bool right_enabled);
        void single_motor_drive(bool left_motor, int input, byte orientation, bool enabled = true);
        void stop();
        void stopLeft();
        void stopRight();


    private:
        DriveMotor leftMotor;
        DriveMotor rightMotor;

        int _minForwardInput;
        int _maxForwardInput;
        int _minLateralInput;
        int _maxLateralInput;
        int _resolution;
        int maxPwmVal;



};


#endif