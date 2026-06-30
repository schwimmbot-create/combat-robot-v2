#ifndef BUTTONS_H
#define BUTTONS_H


#include <Arduino.h>
#include "Constants.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"



class Buttons {
public:
    Buttons(int modeButtonPin);
    void begin();
    ButtonPress checkForPress();

private:
    static void buttonTask(void* pvParams);
    void taskLoop();

    int     modeButtonPin;
    TaskHandle_t taskHandle;

    // Debounce and press-detect state
    bool       lastButtonVal    = HIGH;
    TickType_t lastDebounceTick = 0;
    TickType_t pressTick        = 0;
    bool       pressed          = false;
    bool       eventSent        = false;

    volatile ButtonPress lastEvent = BUTTON_NONE;
};

#endif
