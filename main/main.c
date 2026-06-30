// main.c — ESP-IDF app_main entry point.
//
// Replaces the dual-runtime hack (this file previously called
// btstack_init + uni_init + btstack_run_loop_execute). Now we just
// init the NimBLE gamepad parser and let Arduino's loop() take over.
//
// SPDX-License-Identifier: Apache-2.0

#include <stdio.h>
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "esp_event.h"
#include "esp_netif.h"

#include "ble_gamepad.h"

static const char *TAG = "main";

// Arduino entrypoint. Declared in Arduino.h, defined in sketch.cpp.
void initArduino();

void app_main(void) {
    ESP_LOGI(TAG, "Combat Robot v2 booting");
    ESP_LOGI(TAG, "Free heap: %lu bytes", (unsigned long)esp_get_free_heap_size());

    // NVS must be initialized before any component that uses it.
    // ble_gamepad uses NVS for the MAC whitelist.
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    // TCP/IP stack and event loop are needed for WiFi (used by web_config).
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    // Initialize BLE gamepad parser. Does not start scanning yet —
    // that happens on nimble host sync.
    ESP_ERROR_CHECK(ble_gamepad_init());
    ESP_ERROR_CHECK(ble_gamepad_start());

    // Hand off to Arduino. initArduino() sets up loopTask which runs
    // setup() once, then loop() forever. This call does NOT return;
    // vTaskDelete(NULL) is called inside Arduino's runtime.
    ESP_LOGI(TAG, "Starting Arduino runtime");
    initArduino();
}