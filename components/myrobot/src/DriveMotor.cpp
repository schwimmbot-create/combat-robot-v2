
#include <Constants.h>
#include <Arduino.h>
#include <DriveMotor.h>
#include "esp_log.h"

static const char* TAG = "DriveMotor";


DriveMotor::DriveMotor(byte fwd_pin, byte rev_pin,
                       byte fwd_channel, byte rev_channel,
                       bool flip_direction){
    _fwd_pin = fwd_pin;
    _rev_pin = rev_pin;
    _fwd_channel = fwd_channel;
    _rev_channel = rev_channel;
    _flip_direction = flip_direction;
}

void DriveMotor::begin() {
    // Initialize the PWM channels with the desired frequency and resolution.
    // v2.0.14 Arduino-ESP32 requires: bind pin to channel, then set
    // frequency. v1.3 used a single ledcAttach() call that did both.
    // ledcAttachPin returns void in v2.0.14, so we just call it.
    ledcAttachPin(_fwd_pin, _fwd_channel);
    if (ledcChangeFrequency(_fwd_channel, _pwm_frequency_hz, DRIVE_MOTOR_PWM_RESOLUTION) == 0) {
        ESP_LOGE(TAG, "Failed to set FWD PWM frequency");
    }
    ledcAttachPin(_rev_pin, _rev_channel);
    if (ledcChangeFrequency(_rev_channel, _pwm_frequency_hz, DRIVE_MOTOR_PWM_RESOLUTION) == 0) {
        ESP_LOGE(TAG, "Failed to set REV PWM frequency");
    }
    setSpeed(0, STOP, RIGHTSIDE_UP);
}


void DriveMotor::setPwmFrequency(uint16_t frequency_hz) {
    frequency_hz = constrain(frequency_hz, (uint16_t)1000, (uint16_t)40000);
    if (_pwm_frequency_hz == frequency_hz) return;
    _pwm_frequency_hz = frequency_hz;
    if (ledcChangeFrequency(_fwd_channel, _pwm_frequency_hz, DRIVE_MOTOR_PWM_RESOLUTION) == 0) {
        ESP_LOGE(TAG, "Failed to update FWD PWM frequency");
    }
    if (ledcChangeFrequency(_rev_channel, _pwm_frequency_hz, DRIVE_MOTOR_PWM_RESOLUTION) == 0) {
        ESP_LOGE(TAG, "Failed to update REV PWM frequency");
    }
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


    speed = constrain(speed, (uint16_t)0, (uint16_t)255);
    _speed = speed;
    _direction = direction;

    if(direction == STOP){
        ESP_LOGD(TAG, "Motor Stopped");
        // v2.0.14 ledcWrite returns void; use the explicit channel
        // (not the pin number, which was the v1.3 hack).
        _fwd_duty = 0;
        _rev_duty = 0;
        ledcWrite(_fwd_channel, _fwd_duty);
        ledcWrite(_rev_channel, _rev_duty);
    }
    else if( direction == FORWARD){
        ESP_LOGD(TAG, "Forward: %d", speed);
        _fwd_duty = 255;
        _rev_duty = 255 - speed;
        ledcWrite(_fwd_channel, _fwd_duty);
        ledcWrite(_rev_channel, _rev_duty);
    }
    else if( direction == REVERSE ){
        ESP_LOGD(TAG, "Reverse: %d", speed);
        _fwd_duty = 255 - speed;
        _rev_duty = 255;
        ledcWrite(_fwd_channel, _fwd_duty);
        ledcWrite(_rev_channel, _rev_duty);
    }

}

DriveMotorIntent DriveMotor::getIntent() const {
    return DriveMotorIntent{_speed, _direction, _fwd_duty, _rev_duty, _pwm_frequency_hz};
}



