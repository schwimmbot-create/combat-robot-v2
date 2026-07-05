
#include "LED.h"
#include "Constants.h"
#include "Arduino.h"

LED::LED(int led_pin, unsigned long shortDuration, unsigned long longDuration)
    : led_pin(led_pin), pattern(""), patternIndex(0),
      shortDuration(shortDuration), longDuration(longDuration),
      taskHandle(nullptr), patternQueue(nullptr) {}

void LED::begin() {
    // Drive the pin via plain digitalWrite(). The previous implementation
    // bound the pin to an LEDC channel, which silently disabled
    // digital control of the same pad. That broke the pairing-indicator
    // task (which also writes the same pin) so the LED never blinked
    // even when the pairing callback fired. Plain GPIO control lets
    // the morse-pattern code and the pairing task share the pin without
    // the LEDC peripheral hogging it.
    pinMode(led_pin, OUTPUT);
    digitalWrite(led_pin, LOW);

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
                        digitalWrite(led->led_pin, cmd.dutyCycle ? HIGH : LOW);  // Use brightness from queue
                        vTaskDelay(pdMS_TO_TICKS(symbol == '-' ? led->longDuration : led->shortDuration));
                        digitalWrite(led->led_pin, LOW);
                        vTaskDelay(pdMS_TO_TICKS(200));
                    }
                    if (symbol == '*'){ // Longer duration flash to register on film to indicate synchronization
                        digitalWrite(led->led_pin, cmd.dutyCycle ? HIGH : LOW);  // Use brightness from queue
                        vTaskDelay(pdMS_TO_TICKS(1000));
                        digitalWrite(led->led_pin, LOW);  // Off
                    }
                }

            } while (cmd.repeat);
        }
    }
}