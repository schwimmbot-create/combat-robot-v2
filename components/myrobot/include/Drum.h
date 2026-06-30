// Drum.h
#ifndef DRUM_H
#define DRUM_H

#include <Arduino.h>

class Drum {
public:
    // Constructor: initializes the Drum object with a given pin
    Drum(uint8_t pwmPin);

    void begin();
 
    void setInputLimits(int minInput = 0, int maxInput = 1023);
 
    bool initializeESC();

    void setSpeed(uint16_t forwardValue, uint16_t reverseValue = 0);

    void stop();

private:
    bool escInitialized = false;
    uint8_t _pwmPin;
    uint16_t maxPwmVal;
    uint16_t _minInput;
    uint16_t _maxInput;
};

#endif