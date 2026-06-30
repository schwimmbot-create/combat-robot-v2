
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

void DriveMotor::begin(){
    if(!ledcAttach(_fwd_pin, DRIVE_MOTOR_PWM_FREQ, DRIVE_MOTOR_PWM_RESOLUTION)){ESP_LOGE(TAG, "Failed to initialize Drive Motor FWD PWM Pin");}
    if(!ledcAttach(_rev_pin, DRIVE_MOTOR_PWM_FREQ, DRIVE_MOTOR_PWM_RESOLUTION)){ESP_LOGE(TAG, "Failed to initialize Drive Motor Rev PWM Pin");}
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
        if(!ledcWrite(_fwd_pin, 0)){ESP_LOGE(TAG, "Failed to write Motor PWM");}
        if(!ledcWrite(_rev_pin, 0)){ESP_LOGE(TAG, "Failed to write Motor PWM");}
    }
    else if( direction == FORWARD){
        ESP_LOGD(TAG, "Forward: %d", speed);
        if(!ledcWrite(_fwd_pin, 255)){ESP_LOGE(TAG, "Failed to write Motor PWM");}
        if(!ledcWrite(_rev_pin, 255-speed)){ESP_LOGE(TAG, "Failed to write Motor PWM");}
    }
    else if( direction == REVERSE ){
        ESP_LOGD(TAG, "Reverse: %d", speed);
        if(!ledcWrite(_fwd_pin, 255-speed)){ESP_LOGE(TAG, "Failed to write Motor PWM");}
        if(!ledcWrite(_rev_pin, 255)){ESP_LOGE(TAG, "Failed to write Motor PWM");}
    }

}



