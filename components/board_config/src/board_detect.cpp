// board_detect.cpp — Runtime board revision detection implementation
//
// SPDX-License-Identifier: Apache-2.0

#include "board_detect.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "nvs_flash.h"
#include "nvs.h"

static const char* TAG = "board_detect";

// Active detected rev (set by board_detect_init).
static int s_active_rev = -1;

BoardRevId board_detect_read_id(void) {
    // Configure ID pins as inputs with internal pull-up enabled.
    // This is a one-time setup; the pins stay configured for the rest
    // of boot. If they're used for other purposes later, the firmware
    // should reconfigure them.
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << BOARD_ID_GPIO0) | (1ULL << BOARD_ID_GPIO1),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io_conf);

    // Small delay for signal to settle.
    vTaskDelay(pdMS_TO_TICKS(10));

    // Read the pins.
    int id0 = gpio_get_level((gpio_num_t)BOARD_ID_GPIO0);
    int id1 = gpio_get_level((gpio_num_t)BOARD_ID_GPIO1);

    ESP_LOGD(TAG, "Board ID pins: ID0=%d ID1=%d", id0, id1);

    // 2-bit ID. Maps:
    //   0b00 -> v2
    //   0b01 -> v3
    //   0b10 -> v4 (future)
    //   0b11 -> v5 (future)
    int id_bits = (id1 << 1) | id0;
    switch (id_bits) {
        case 0b00: return BOARD_REV_ID_V2;
        case 0b01: return BOARD_REV_ID_V3;
        case 0b10: return BOARD_REV_ID_V4;
        case 0b11: return BOARD_REV_ID_V5;
        default:   return BOARD_REV_ID_UNKNOWN;
    }
}

int board_detect_id_to_rev(BoardRevId id) {
    switch (id) {
        case BOARD_REV_ID_V2: return 2;
        case BOARD_REV_ID_V3: return 3;
        case BOARD_REV_ID_V4: return 4;
        case BOARD_REV_ID_V5: return 5;
        default:              return 0;
    }
}

int board_detect_active_rev(void) {
    if (s_active_rev > 0) return s_active_rev;
    // Fall back to compile-time value
    return BOARD_REV;
}

void board_detect_init(void) {
    ESP_LOGI(TAG, "Board detection starting...");

    // 1. Check NVS for user override.
    nvs_handle_t h;
    esp_err_t err = nvs_open("board_config", NVS_READONLY, &h);
    int nvs_rev = 0;
    if (err == ESP_OK) {
        nvs_get_i32(h, "rev_override", &nvs_rev);
        nvs_close(h);
    }
    if (nvs_rev > 0) {
        ESP_LOGI(TAG, "Board rev override from NVS: %d", nvs_rev);
        s_active_rev = nvs_rev;
        return;
    }

    // 2. Try hardware strapping detection.
    BoardRevId id = board_detect_read_id();
    if (id != BOARD_REV_ID_UNKNOWN) {
        int rev = board_detect_id_to_rev(id);
        ESP_LOGI(TAG, "Detected board: %s (rev %d, ID=0x%02x)",
                 BOARD_NAME, rev, id);
        s_active_rev = rev;
        return;
    }

    // 3. Fall back to compile-time default.
    ESP_LOGW(TAG, "Board detection failed, using compile-time BOARD_REV=%d", BOARD_REV);
    s_active_rev = BOARD_REV;
}

// Runtime override API (used by web UI)
esp_err_t board_detect_set_override(int rev) {
    nvs_handle_t h;
    esp_err_t err = nvs_open("board_config", NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    err = nvs_set_i32(h, "rev_override", rev);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}

esp_err_t board_detect_clear_override(void) {
    nvs_handle_t h;
    esp_err_t err = nvs_open("board_config", NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    err = nvs_erase_key(h, "rev_override");
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}