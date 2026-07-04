// web_config.h — Async web server + WiFi manager + HTML UI
//
// Replaces v1.3 WebInterface.cpp (broken) and OtaUpdater.cpp.
//
// Architecture:
//   * ESPAsyncWebServer runs on a dedicated task; never blocks the
//     main loop.
//   * WiFi manager tries saved STA credentials first; falls back to
//     AP mode with captive portal.
//   * HTML/CSS/JS embedded as PROGMEM strings (no SPIFFS needed for v1).
//   * REST API for pairing, status, OTA. Motor/pin config API in v2.
//
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

// Initialize WiFi (AP+STA), HTTP server, DNS for captive portal.
// Must be called AFTER nvs_flash_init() and esp_netif_init().
// Returns ESP_OK on success.
esp_err_t web_config_init(void);

// Call periodically from a low-priority task to handle DNS queries.
// (ESPAsyncWebServer handles HTTP, but the captive portal needs a
//  DNS server that responds to all names with our IP. We run a
//  minimal DNS server on port 53.)
void web_config_loop(void);

// Status query — used by /api/status.
struct web_status_t {
    bool ble_connected;
    bool wifi_connected;
    bool wifi_ap_mode;
    char wifi_ip[16];
    char ble_mac[18];      // "AA:BB:CC:DD:EE:FF" or "—"
    char paired_count[4];
    uint16_t battery_mv;   // millivolts
    uint8_t battery_state; // 1=good 2=warn 3=low
    const char *pairing_state_str;
    const char *firmware_version;
};

void web_config_get_status(web_status_t *out);

#ifdef __cplusplus
}  // extern "C"
#endif