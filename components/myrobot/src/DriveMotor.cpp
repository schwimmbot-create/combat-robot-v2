
#include <Constants.h>
#include <Arduino.h>
#include <DriveMotor.h>
#include "esp_log.h"

static const char* TAG = "DriveMotor";


DriveMotor::DriveMotor(byte fwd_pin, byte rev_pin, bool flip_direction){
    _fwd_pin = fwd_pin;
    _rev_pin = rev_pin;
    _flip_direction = flip_direction;
}

void DriveMotor::begin() {
    // Initialize the PWM channels with the desired frequency and resolution.
    // v2.0.14 Arduino-ESP32 requires: bind pin to channel, then set
    // frequency. v1.3 used a single ledcAttach() call that did both.
    // ledcAttachPin returns void in v2.0.14, so we just call it.
    ledcAttachPin(_fwd_pin, DRIVE_MOTOR_FWD_PWM_CHANNEL);
    if (ledcChangeFrequency(DRIVE_MOTOR_FWD_PWM_CHANNEL, DRIVE_MOTOR_PWM_FREQ, DRIVE_MOTOR_PWM_RESOLUTION) == 0) {
        ESP_LOGE(TAG, "Failed to set FWD PWM frequency");
    }
    ledcAttachPin(_rev_pin, DRIVE_MOTOR_REV_PWM_CHANNEL);
    if (ledcChangeFrequency(DRIVE_MOTOR_REV_PWM_CHANNEL, DRIVE_MOTOR_PWM_FREQ, DRIVE_MOTOR_PWM_RESOLUTION) == 0) {
        ESP_LOGE(TAG, "Failed to set REV PWM frequency");
    }
    setSpeed(0, STOP, RIGHTSIDE_UP);
}

/**
 * Sets the speed of an individual drive motor
 * @param speed         Motor Speed between 0-255 
 * @param direction     FORWARD, REVERSE, or STOP
 * @param orientation   Declare whether the robot is rightside up or upside down
 */
void DriveMotor::setSpeed(uint16_t speed, byte direction, byte orientation){

    //Flip motor direction to correct for wiring polarity differences
    if( _flip_direction == true){
        if(direction == FORWARD){direction = REVERSE;}
        else if (direction == REVERSE){direction = FORWARD;}    
    }

    //Flip motor direction to adjust for orientation (CW to CCW)
    //Correction for Left<->Right side swapping is done in Drive.cpp
    if(orientation == UPSIDE_DOWN){
        if(direction == FORWARD){direction = REVERSE;}
        else if (direction == REVERSE){direction = FORWARD;}    
    }


    if(direction == STOP){
        ESP_LOGD(TAG, "Motor Stopped");
        // v2.0.14 ledcWrite returns void; use the explicit channel
        // (not the pin number, which was the v1.3 hack).
        ledcWrite(DRIVE_MOTOR_FWD_PWM_CHANNEL, 0);
        ledcWrite(DRIVE_MOTOR_REV_PWM_CHANNEL, 0);
    }
    else if( direction == FORWARD){
        ESP_LOGD(TAG, "Forward: %d", speed);
        ledcWrite(DRIVE_MOTOR_FWD_PWM_CHANNEL, 255);
        ledcWrite(DRIVE_MOTOR_REV_PWM_CHANNEL, 255-speed);
    }
    else if( direction == REVERSE ){
        ESP_LOGD(TAG, "Reverse: %d", speed);
        ledcWrite(DRIVE_MOTOR_FWD_PWM_CHANNEL, 255-speed);
        ledcWrite(DRIVE_MOTOR_REV_PWM_CHANNEL, 255);
    }

}



