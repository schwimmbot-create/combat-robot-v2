#include "PowerFunctions.h"
#include "Constants.h"
#include "battery_config.h"
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include "esp_task_wdt.h"

static const char* TAG = "PowerFunctions";

static constexpr uint16_t BATTERY_EMPTY_MV_PER_CELL = 3300;
static constexpr uint16_t BATTERY_FULL_MV_PER_CELL = 4200;
static constexpr uint16_t BATTERY_WARN_MARGIN_MV_PER_CELL = 150;

static volatile uint16_t s_lastBatteryMillivolts = 0;
static volatile uint8_t s_lastBatteryPercent = 0;
static volatile uint8_t s_lastBatteryState = BATTERY_GOOD;

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
    battery_config_init();

    // ADC setup
    analogReadResolution(12);

    // Compute cutoff from runtime battery config. The default maps to the
    // old 3.60 V/cell behavior for a 3S LiPo.
    shutdownVoltage_mV = battery_cutoff_millivolts(
        battery_config_get_cell_count(),
        battery_config_get_cutoff_percent());
    ESP_LOGI(TAG, "Shutdown Voltage Set: %d mV", shutdownVoltage_mV);

    // Init EMA to a safe starting point
    ema_mV = shutdownVoltage_mV;
    s_lastBatteryMillivolts = (uint16_t)shutdownVoltage_mV;
    s_lastBatteryPercent = battery_config_get_cutoff_percent();
    s_lastBatteryState = BATTERY_GOOD;

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

uint16_t PowerFunctions::getBatteryMillivolts() const {
    return (uint16_t)ema_mV;
}

uint16_t PowerFunctions::getLastBatteryMillivolts() {
    return s_lastBatteryMillivolts;
}

uint8_t PowerFunctions::getLastBatteryPercent() {
    return s_lastBatteryPercent;
}

uint8_t PowerFunctions::getLastBatteryState() {
    return s_lastBatteryState;
}

uint16_t PowerFunctions::battery_cutoff_millivolts(uint8_t cell_count, uint8_t cutoff_percent) {
    if (cell_count == 0) cell_count = BC_CELL_COUNT_DEFAULT;
    if (cutoff_percent > 100) cutoff_percent = 100;
    const uint32_t span = BATTERY_FULL_MV_PER_CELL - BATTERY_EMPTY_MV_PER_CELL;
    const uint32_t per_cell = BATTERY_EMPTY_MV_PER_CELL + ((span * cutoff_percent) / 100);
    return (uint16_t)(per_cell * cell_count);
}

uint8_t PowerFunctions::battery_percent_from_millivolts(uint16_t millivolts, uint8_t cell_count) {
    if (cell_count == 0 || millivolts == 0) return 0;
    const uint32_t per_cell = (uint32_t)millivolts / cell_count;
    if (per_cell <= BATTERY_EMPTY_MV_PER_CELL) return 0;
    if (per_cell >= BATTERY_FULL_MV_PER_CELL) return 100;
    return (uint8_t)(((per_cell - BATTERY_EMPTY_MV_PER_CELL) * 100) /
                     (BATTERY_FULL_MV_PER_CELL - BATTERY_EMPTY_MV_PER_CELL));
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

    static TickType_t lowSince = 0;

    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));

    for (;;) {

        float raw_mV = self->readBatteryVoltage();

        self->ema_mV = EMA_ALPHA * raw_mV
                     + (1.0f - EMA_ALPHA) * self->ema_mV;

        const uint8_t cells = battery_config_get_cell_count();
        const uint8_t cutoffPercent = battery_config_get_cutoff_percent();
        const int lowVoltage_mV = battery_cutoff_millivolts(cells, cutoffPercent);
        const int warnVoltage_mV = min(
            (int)(BATTERY_FULL_MV_PER_CELL * cells),
            lowVoltage_mV + (int)(BATTERY_WARN_MARGIN_MV_PER_CELL * cells));
        self->shutdownVoltage_mV = lowVoltage_mV;

        const uint16_t filtered_mV = (uint16_t)max(0.0f, self->ema_mV);
        s_lastBatteryMillivolts = filtered_mV;
        s_lastBatteryPercent = battery_percent_from_millivolts(filtered_mV, cells);

        ESP_LOGD(TAG, "Filtered Batt V (mV): %.2f", self->ema_mV);

        // --- Debounce for LOW ---
        if (self->ema_mV <= lowVoltage_mV) {
            if (lowSince == 0) lowSince = xTaskGetTickCount();
            if (xTaskGetTickCount() - lowSince >= pdMS_TO_TICKS(BATTERY_DEBOUNCE_TIME)) {
                self->batteryState = BATTERY_LOW;
                s_lastBatteryState = BATTERY_LOW;
                ESP_LOGD(TAG, "Battery LOW");
            }
        } else {
            lowSince = 0;

            // --- Hysteresis for WARN/GOOD ---
            if (self->ema_mV <= warnVoltage_mV) {
                self->batteryState = BATTERY_WARN;
                s_lastBatteryState = BATTERY_WARN;
                ESP_LOGD(TAG, "Battery WARNING");
            } else if (self->ema_mV >= warnVoltage_mV + BATT_HYSTERESIS) {
                self->batteryState = BATTERY_GOOD;
                s_lastBatteryState = BATTERY_GOOD;
            }
        }

        ESP_ERROR_CHECK(esp_task_wdt_reset());   // feed for THIS task
        vTaskDelayUntil(&lastWake, pdMS_TO_TICKS(BATT_READ_FREQ));
    }
}
