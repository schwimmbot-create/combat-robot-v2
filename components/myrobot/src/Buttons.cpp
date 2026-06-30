#include "Buttons.h"
#include "Constants.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_task_wdt.h"



Buttons::Buttons(int modeButtonPin)
  : modeButtonPin(modeButtonPin)
{}

void Buttons::begin() {
    // Configure the button pin
    pinMode(modeButtonPin, INPUT_PULLUP);

    // Start the FreeRTOS task
    xTaskCreate(
        buttonTask,
        "BtnTask",
        2048,
        this,
        1,
        &taskHandle
    );
}

// Static task entrypoint
void Buttons::buttonTask(void* pvParams) {
    static_cast<Buttons*>(pvParams)->taskLoop();
}

// Task loop: polls, debounces, and updates lastEvent
void Buttons::taskLoop() {
    TickType_t lastWake        = xTaskGetTickCount();
    const TickType_t debounceTicks  = pdMS_TO_TICKS(DEBOUNCE_TIME);
    const TickType_t longPressTicks = pdMS_TO_TICKS(LONG_PRESS_TIME);
    const TickType_t pollInterval   = pdMS_TO_TICKS(BUTTON_READ_WAIT);

    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));

    for (;;) {
        TickType_t now = xTaskGetTickCount();
        bool currentVal = digitalRead(modeButtonPin);

        // Debounce: detect stable state changes
        if (currentVal != lastButtonVal) {
            lastDebounceTick = now;
            lastButtonVal = currentVal;
        } else if (now - lastDebounceTick >= debounceTicks) {
            // Button pressed logic level
            if (currentVal == BUTTON_LOGIC_LEVEL) {
                if (!pressed) {
                    // first stable press
                    pressed   = true;
                    eventSent = false;
                    pressTick = now;
                } else if (eventSent == false && (now - pressTick >= longPressTicks)) {
                    lastEvent = BUTTON_LONG;
                    eventSent = true;
                }
            } else {
                // Button release
                if (pressed == true && eventSent == false) {
                    lastEvent = BUTTON_SHORT;
                }
                pressed   = false;
                eventSent = true;
            }
        }

        ESP_ERROR_CHECK(esp_task_wdt_reset());   // feed for THIS task
        vTaskDelayUntil(&lastWake, pollInterval);
    }
}

// Fetch the most recent event, then clear it
ButtonPress Buttons::checkForPress() {
    ButtonPress evt = lastEvent;
    lastEvent = BUTTON_NONE;
    return evt;
}

