
#include "LED.h"
#include "Constants.h"
#include "Arduino.h"

LED::LED(int led_pin, unsigned long shortDuration, unsigned long longDuration)
    : led_pin(led_pin), pattern(""), patternIndex(0),
      shortDuration(shortDuration), longDuration(longDuration),
      taskHandle(nullptr), patternQueue(nullptr) {}

void LED::begin() {
    // v2.0.14 Arduino-ESP32: bind pin to channel, then set frequency.
    ledcAttachPin(led_pin, LED_PWM_CHANNEL);
    ledcChangeFrequency(LED_PWM_CHANNEL, 2000, 8);
    ledcWrite(LED_PWM_CHANNEL, 0);


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
                        ledcWrite(LED_PWM_CHANNEL, cmd.dutyCycle);  // Use brightness from queue
                        vTaskDelay(pdMS_TO_TICKS(symbol == '-' ? led->longDuration : led->shortDuration));

                        //ledcWrite(1, 0);  // Off between pulses
                        ledcWrite(LED_PWM_CHANNEL, 0);
                        vTaskDelay(pdMS_TO_TICKS(200));
                    }
                    if (symbol == '*'){ // Longer duration flash to register on film to indicate synchronization
                        ledcWrite(LED_PWM_CHANNEL, cmd.dutyCycle);  // Use brightness from queue
                        vTaskDelay(pdMS_TO_TICKS(1000));
                        ledcWrite(LED_PWM_CHANNEL, 0);  // Off 
                    }
                }

            } while (cmd.repeat);
        }
    }
}