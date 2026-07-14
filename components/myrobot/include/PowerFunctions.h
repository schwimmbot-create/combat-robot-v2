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
    uint16_t getBatteryMillivolts() const;

    static uint16_t getLastBatteryMillivolts();
    static uint8_t getLastBatteryPercent();
    static uint8_t getLastBatteryState();
    static uint16_t battery_cutoff_millivolts(uint8_t cell_count, uint8_t cutoff_percent);
    static uint16_t battery_warn_millivolts(uint8_t cell_count, uint8_t warn_percent);
    static uint8_t battery_percent_from_millivolts(uint16_t millivolts, uint8_t cell_count);

#ifdef BENCH_HID_PUBLIC
    static void benchSetBatteryOverride(uint8_t state, uint8_t percent);
    static void benchClearBatteryOverride();
    static bool benchBatteryOverrideEnabled();
#endif

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