// board_detect.cpp — NVS-based board revision selection
//
// SPDX-License-Identifier: Apache-2.0

#include "board_detect.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "nvs.h"

static const char* TAG = "board_detect";

#define NVS_NAMESPACE    "board_config"
#define NVS_KEY_OVERRIDE "rev_override"

int board_detect_id_to_rev(BoardRevId id) {
    switch (id) {
        case BOARD_REV_ID_V2: return 2;
        case BOARD_REV_ID_V3: return 3;
        default:              return 0;
    }
}

bool board_detect_has_override(int *out_rev) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &h);
    if (err != ESP_OK) return false;

    int32_t rev = 0;
    err = nvs_get_i32(h, NVS_KEY_OVERRIDE, &rev);
    nvs_close(h);

    if (err != ESP_OK) return false;
    if (out_rev) *out_rev = (int)rev;
    return true;
}

int board_detect_active_rev(void) {
    int override = 0;
    if (board_detect_has_override(&override) && override > 0) {
        ESP_LOGD(TAG, "Using NVS board rev override: %d", override);
        return override;
    }
    // Fall back to compile-time default.
    ESP_LOGD(TAG, "Using compile-time BOARD_REV=%d", BOARD_REV);
    return BOARD_REV;
}

esp_err_t board_detect_set_override(int rev) {
    if (rev < 2 || rev > 255) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    err = nvs_set_i32(h, NVS_KEY_OVERRIDE, (int32_t)rev);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "Board rev override set to %d (takes effect on next boot)", rev);
    }
    return err;
}

esp_err_t board_detect_clear_override(void) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    err = nvs_erase_key(h, NVS_KEY_OVERRIDE);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "Board rev override cleared (will use compile-time BOARD_REV=%d)", BOARD_REV);
    }
    return err;
}