#ifndef POWER_FUNCTIONS_H
#define POWER_FUNCTIONS_H

#include "Constants.h"
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

class PowerFunctions {
public:
    PowerFunctions();
    void begin();
    int getBatteryState() const;

private:
    static void batteryMonitorTask(void* pvParameters);
    float readBatteryVoltage();

    uint32_t shutdownVoltage_mV;
    TaskHandle_t monitorTaskHandle;

    // EMA state & parameter:
    float ema_mV;  
    //static constexpr float EMA_ALPHA = 0.1f;  

    volatile uint8_t batteryState = BATTERY_GOOD;
    TickType_t samplePeriodTicks;
};

#endif