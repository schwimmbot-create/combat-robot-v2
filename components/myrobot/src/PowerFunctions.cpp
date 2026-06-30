#include "PowerFunctions.h"
#include "Constants.h"
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include "esp_task_wdt.h"

static const char* TAG = "PowerFunctions";

PowerFunctions::PowerFunctions()
  : shutdownVoltage_mV(0),
    monitorTaskHandle(nullptr),
    ema_mV(0),
    batteryState(BATTERY_GOOD),
    samplePeriodTicks(0)
{}

/**
 * @brief  Initialize ADC and start the battery‐monitoring task.
 * 
 * Calculates the shutdown voltage (in mV) based on 
 * MIN_MVOLT_PER_CELL × NUM_OF_CELLS, then spins up 
 * a FreeRTOS task to keep checking battery level.
 */
void PowerFunctions::begin() {
    // ADC setup
    analogReadResolution(12);

    // Compute cutoff
    shutdownVoltage_mV = MIN_MVOLT_PER_CELL * NUM_OF_CELLS;
    ESP_LOGI(TAG, "Shutdown Voltage Set: %d mV", shutdownVoltage_mV);

    // Init EMA to a safe starting point
    ema_mV = shutdownVoltage_mV;

    samplePeriodTicks = pdMS_TO_TICKS(SAMPLE_PERIOD);

    // Spawn monitor task
    xTaskCreatePinnedToCore(
        batteryMonitorTask,
        "BatteryMonitor",
        4096,
        this,
        tskIDLE_PRIORITY + 1,
        &monitorTaskHandle,
        APP_CPU_NUM
    );
}

/**
 * @brief  Get the last known battery state.
 * 
 * @return BATTERY_GOOD, BATTERY_WARN, or BATTERY_LOW
 */
int PowerFunctions::getBatteryState() const {
    return batteryState;
}

// Burst-read or delayed-read ADC as before
float PowerFunctions::readBatteryVoltage() {
    uint32_t rawSum = 0;
    for (uint8_t i = 0; i < BATT_SAMPLE_COUNT; ++i) {
        rawSum += analogRead(BATT_MEAS_PIN);
        vTaskDelay(samplePeriodTicks);
    }
    float avgRaw = float(rawSum) / BATT_SAMPLE_COUNT;
    float volts  = avgRaw * (3.3f / 4095.0f);
    return volts * 1000.0f * BATTERY_MULTIPLIER;
}

/**
 * @brief      RTOS task: periodically samples the battery ADC.
 * @param[in]  pvParameters  A pointer to the PowerFunctions instance (i.e. `this`).
 * 
 * This task will sleep for BATT_READ_FREQ ms between samples.
 * @note       Uses analogReadResolution(12) and BATT_SAMPLE_COUNT samples.
 */
void PowerFunctions::batteryMonitorTask(void* pvParameters) {
    auto* self = static_cast<PowerFunctions*>(pvParameters);
    TickType_t lastWake = xTaskGetTickCount();

    const int warnVoltage_mV = WARN_MVOLT_PER_CELL * NUM_OF_CELLS;
    const int lowVoltage_mV  = MIN_MVOLT_PER_CELL * NUM_OF_CELLS;

    static TickType_t lowSince = 0;

    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));

    for (;;) {

        float raw_mV = self->readBatteryVoltage();

        self->ema_mV = EMA_ALPHA * raw_mV
                     + (1.0f - EMA_ALPHA) * self->ema_mV;

        ESP_LOGD(TAG, "Filtered Batt V (mV): %.2f", self->ema_mV);

        // --- Debounce for LOW ---
        if (self->ema_mV <= lowVoltage_mV) {
            if (lowSince == 0) lowSince = xTaskGetTickCount();
            if (xTaskGetTickCount() - lowSince >= pdMS_TO_TICKS(BATTERY_DEBOUNCE_TIME)) {
                self->batteryState = BATTERY_LOW;
                ESP_LOGD(TAG, "Battery LOW");
            }
        } else {
            lowSince = 0;

            // --- Hysteresis for WARN/GOOD ---
            if (self->ema_mV <= warnVoltage_mV) {
                self->batteryState = BATTERY_WARN;
                ESP_LOGD(TAG, "Battery WARNING");
            } else if (self->ema_mV >= warnVoltage_mV + BATT_HYSTERESIS) {
                self->batteryState = BATTERY_GOOD;
            }
        }

        ESP_ERROR_CHECK(esp_task_wdt_reset());   // feed for THIS task
        vTaskDelayUntil(&lastWake, pdMS_TO_TICKS(BATT_READ_FREQ));
    }
}
