#include "Drum.h"
#include "Constants.h"
#include <Arduino.h>
#include "esp_log.h"

static const char* TAG = "Drum";

Drum::Drum(uint8_t pwmPin) : _pwmPin(pwmPin) {
    setInputLimits();
}

void Drum::begin() {
    // Initialize the PWM channel with the desired frequency and resolution.
    // v2.0.14 Arduino-ESP32 requires: bind pin to channel, then set
    // frequency. v1.3 used a single ledcAttach() call that did both.
    ledcAttachPin(_pwmPin, ESC_PWM_CHANNEL);
    ledcChangeFrequency(ESC_PWM_CHANNEL, ESC_PWM_FREQ, ESC_PWM_RESOLUTION);

    //Caluclate the maximuum value that may be sent given the resolution of the PWM
    maxPwmVal = (1 << ESC_PWM_RESOLUTION)-1;

    //initializeESC
    while(!initializeESC());

    // Initialize ESC with a neutral signal
    setSpeed(0);
}


/**
 * Sets the minimum and maximum expected input values that will be recieved from the controller.
 * Default: 0 to 1023
 * @param minInput      Minimum input value from the controller
 * @param maxInput      Maximum input value from the controller
 */
void Drum::setInputLimits(int minInput, int maxInput){
    _minInput = minInput;
    _maxInput = maxInput;
}

//Function to initialize the ESC on start up
//The function is non-blocking so must be performed in a loop and returns True when complete
bool Drum::initializeESC(){
    //If ESC is already initialized, don't initialize again
    if(escInitialized == true ){
        return true;
    }

    static bool initializationStarted = false;
    static uint32_t start_time;
    if( initializationStarted == false){
        initializationStarted = true;
        setSpeed(maxPwmVal/ESC_INITIALIZE_FRACTION);
        start_time = millis();
    }
    if( millis() - start_time >= ESC_INITIALIZE_WAIT_TIME && initializationStarted == true){
        setSpeed(0);
        escInitialized = true;
        return true;
    }
    return false;
    
}

/**
 * Sets the drum speed with the input from the controller value
 * @param forwardValue     The forward speed input value between Min and Max Input
 * @param reverseValue     The reverse speed input value between Min and Max Input (Optional, default = 0)
 */
void Drum::setSpeed(uint16_t forwardValue, uint16_t reverseValue) {
    // Ensure throttlePercent is within the valid range
    uint16_t forwardSpeedInput = constrain(forwardValue, _minInput, _maxInput);
    uint16_t reverseSpeedInput = constrain(reverseValue, _minInput, _maxInput);

    // Map the speed value to the appropriate pulsewidth 
    //If unidirectional, map between ESC_MIN_PULSEWIDTH and ESC_MAX_PULSEWIDTH
    uint16_t pulseWidthUs;
    if(WEAPON_BIDIRECTIONAL == false){
        pulseWidthUs = map(forwardSpeedInput, _minInput, _maxInput, ESC_MIN_PULSEWIDTH, ESC_MAX_PULSEWIDTH);
    }
    else{
        //If Forward speed is greater than 10% of maxInput and Reverse Speed is Less than Forward Speed, then spin Forward
        if((forwardSpeedInput > (_maxInput / 10)) && (reverseSpeedInput < forwardSpeedInput)){
            pulseWidthUs = map(forwardSpeedInput, _minInput, _maxInput, ESC_MID_PULSEWIDTH, ESC_MAX_PULSEWIDTH);
        }
        //Otherwise, spin Reverse with 0 being max reverse and MID_PULSEWIDTH being stopped
        else{
            pulseWidthUs = map(reverseSpeedInput, _minInput, _maxInput, ESC_MID_PULSEWIDTH, ESC_MIN_PULSEWIDTH); 
        }
    }

    //Convert the pulse width in µs to a duty cycle for the given frequency that is set
    uint16_t duty_cycle = (pulseWidthUs * maxPwmVal) / (1000000 / ESC_PWM_FREQ);
    ESP_LOGD(TAG, "ESC Duty Cycle: %d\tESC Pulse Width: %d uSec", duty_cycle, pulseWidthUs);
    

    // Use ledcWrite (returns void in v2.0.14) to send the PWM signal.
    // v1.3 used ledcWrite(pin, duty) treating the pin as the channel;
    // v2.0.14 requires the explicit LEDC channel number.
    ledcWrite(ESC_PWM_CHANNEL, duty_cycle);
}

//Stop the drum by sending the minimum pulse width signal.
//Stopping the signal altogether would not stop the ESC from it's last recieved value
void Drum::stop(){
    setSpeed(_minInput);
}
