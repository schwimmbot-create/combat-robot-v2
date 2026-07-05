// battery_config.h — NVS-backed battery safety configuration
//
// Stores runtime-tunable pack assumptions used by PowerFunctions and the
// web UI: LiPo cell count and the estimated percent remaining at low-voltage
// cutoff. Physical ADC pin/divider values stay in Constants.h.
//
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <stdint.h>
#include <stddef.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define BC_NVS_NAMESPACE          "battery_cfg"
#define BC_NVS_KEY_CELL_COUNT     "cells_v1"
#define BC_NVS_KEY_CUTOFF_PERCENT "cutoff_pct_v1"

#define BC_CELL_COUNT_DEFAULT       3
#define BC_CELL_COUNT_MIN           1
#define BC_CELL_COUNT_MAX           8

// Default mirrors the old 3.60 V/cell cutoff when using the 3.30–4.20 V
// percent model: (3.60 - 3.30) / (4.20 - 3.30) ~= 33%.
#define BC_CUTOFF_PERCENT_DEFAULT  33
#define BC_CUTOFF_PERCENT_MIN       0
#define BC_CUTOFF_PERCENT_MAX      80

#define BC_JSON_BUF_SIZE          256

typedef struct {
    uint8_t cell_count;
    uint8_t cutoff_percent;
} battery_config_t;

esp_err_t battery_config_init(void);
void battery_config_reset_defaults(void);

uint8_t battery_config_get_cell_count(void);
uint8_t battery_config_get_cutoff_percent(void);
esp_err_t battery_config_set_cell_count(uint8_t cells);
esp_err_t battery_config_set_cutoff_percent(uint8_t percent);
esp_err_t battery_config_commit(void);

int battery_config_to_json(char *out_buf, size_t out_buf_len);
esp_err_t battery_config_apply_json_patch(const char *json_patch);

#ifdef __cplusplus
}
#endif
