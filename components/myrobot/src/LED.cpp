
#include "LED.h"
#include "Constants.h"
#include "Arduino.h"

LED::LED(int led_pin, unsigned long shortDuration, unsigned long longDuration)
    : led_pin(led_pin), pattern(""), patternIndex(0),
      shortDuration(shortDuration), longDuration(longDuration),
      taskHandle(nullptr), patternQueue(nullptr) {}

void LED::begin() {
    //ledcSetup(1, 20000, 8);
    //ledcAttachPin(led_pin, 1);
    ledcAttach(led_pin, 2000, 8);     // 5kHz, 8-bit resolution
    //ledcWrite(1, 0);           // Start off
    ledcWrite(led_pin, 0);


    patternQueue = xQueueCreate(5, sizeof(PatternCommand));

#if CONFIG_FREERTOS_UNICORE
    xTaskCreate(patternTask, "LEDTask", 2048, this, 1, &taskHandle);
#else
    xTaskCreatePinnedToCore(patternTask, "LEDTask", 2048, this, 1, &taskHandle, APP_CPU_NUM);
#endif
}

void LED::enqueuePattern(const char* newPattern, bool repeat, uint8_t dutyCycle) {
    PatternCommand cmd = { newPattern, repeat, dutyCycle };
    xQueueReset(patternQueue);  // Clear any existing patterns
    xQueueSend(patternQueue, &cmd, portMAX_DELAY);
}

void LED::advancePattern() {
    patternIndex++;
    if (pattern[patternIndex] == '\0') {
        patternIndex = 0;
    }
}

void LED::patternTask(void* pvParameters) {
    LED* led = static_cast<LED*>(pvParameters);
    PatternCommand cmd;

    while (true) {
        if (xQueueReceive(led->patternQueue, &cmd, portMAX_DELAY)) {
            do {
                led->pattern = cmd.pattern;
                led->patternIndex = 0;

                while (led->pattern[led->patternIndex] != '\0') {
                    char symbol = led->pattern[led->patternIndex++];
                    if (symbol == '.' || symbol == '-') {
                        //ledcWrite(1, cmd.dutyCycle);  // Use brightness from queue
                        ledcWrite(led->led_pin, cmd.dutyCycle);  // Use brightness from queue
                        vTaskDelay(pdMS_TO_TICKS(symbol == '-' ? led->longDuration : led->shortDuration));

                        //ledcWrite(1, 0);  // Off between pulses
                        ledcWrite(led->led_pin, 0);
                        vTaskDelay(pdMS_TO_TICKS(200));
                    }
                    if (symbol == '*'){ // Longer duration flash to register on film to indicate synchronization
                        ledcWrite(led->led_pin, cmd.dutyCycle);  // Use brightness from queue
                        vTaskDelay(pdMS_TO_TICKS(1000));
                        ledcWrite(led->led_pin, 0);  // Off 
                    }
                }

            } while (cmd.repeat);
        }
    }
}