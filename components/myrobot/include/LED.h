#ifndef LED_H
#define LED_H

#include <Arduino.h>
#include "Constants.h"
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/queue.h>

struct PatternCommand {
    const char* pattern;
    bool repeat;
    uint8_t dutyCycle; // New: brightness for this pattern (0–255)
};

class LED {
public:
    LED(int led_pin, unsigned long shortDuration = 200, unsigned long longDuration = 600);

    void begin();
    void enqueuePattern(const char* pattern, bool repeat = false, uint8_t dutyCycle = 255); // New parameter

private:
    int led_pin;
    const char* pattern;
    int patternIndex;
    unsigned long shortDuration;
    unsigned long longDuration;
    TaskHandle_t taskHandle;
    QueueHandle_t patternQueue;

    void advancePattern();
    static void patternTask(void* pvParameters);
};

#endif // LED_H