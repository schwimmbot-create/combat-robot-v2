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
    void setHoldTimeMs(uint16_t holdMs);

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
    bool       longEventSent    = false;
    bool       hold5sEventSent  = false;
    bool       shortPending     = false;
    TickType_t shortPendingTick = 0;
    uint16_t   holdTimeMs       = HOLD_5S_TIME;

    volatile ButtonPress lastEvent = BUTTON_NONE;
};

#endif
