// battery_config.c — NVS-backed battery safety configuration
//
// Keep this dependency-light like output_config: small hand-rolled JSON and
// simple u8 NVS keys so future schema changes don't invalidate old output_cfg.

#include "battery_config.h"

#include <ctype.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "battery_config";

static battery_config_t s_cfg = {
    .cell_count = BC_CELL_COUNT_DEFAULT,
    .cutoff_percent = BC_CUTOFF_PERCENT_DEFAULT,
    .warn_percent = BC_WARN_PERCENT_DEFAULT,
};
static bool s_loaded = false;

static bool valid_cells(uint8_t cells) {
    return cells >= BC_CELL_COUNT_MIN && cells <= BC_CELL_COUNT_MAX;
}

static bool valid_cutoff(uint8_t percent) {
    return percent >= BC_CUTOFF_PERCENT_MIN && percent <= BC_CUTOFF_PERCENT_MAX;
}

static bool valid_warn(uint8_t percent, uint8_t cutoff_percent) {
    return percent >= BC_WARN_PERCENT_MIN && percent <= BC_WARN_PERCENT_MAX && percent > cutoff_percent;
}

static esp_err_t save_all(void) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(BC_NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }
    err = nvs_set_u8(h, BC_NVS_KEY_CELL_COUNT, s_cfg.cell_count);
    if (err == ESP_OK) err = nvs_set_u8(h, BC_NVS_KEY_CUTOFF_PERCENT, s_cfg.cutoff_percent);
    if (err == ESP_OK) err = nvs_set_u8(h, BC_NVS_KEY_WARN_PERCENT, s_cfg.warn_percent);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    if (err != ESP_OK) ESP_LOGE(TAG, "nvs_set/commit failed: %s", esp_err_to_name(err));
    return err;
}

void battery_config_reset_defaults(void) {
    s_cfg.cell_count = BC_CELL_COUNT_DEFAULT;
    s_cfg.cutoff_percent = BC_CUTOFF_PERCENT_DEFAULT;
    s_cfg.warn_percent = BC_WARN_PERCENT_DEFAULT;
}

esp_err_t battery_config_init(void) {
    if (s_loaded) return ESP_OK;
    battery_config_reset_defaults();

    nvs_handle_t h;
    esp_err_t err = nvs_open(BC_NVS_NAMESPACE, NVS_READONLY, &h);
    if (err == ESP_OK) {
        uint8_t v = 0;
        if (nvs_get_u8(h, BC_NVS_KEY_CELL_COUNT, &v) == ESP_OK && valid_cells(v)) {
            s_cfg.cell_count = v;
        }
        if (nvs_get_u8(h, BC_NVS_KEY_CUTOFF_PERCENT, &v) == ESP_OK && valid_cutoff(v)) {
            s_cfg.cutoff_percent = v;
        }
        if (nvs_get_u8(h, BC_NVS_KEY_WARN_PERCENT, &v) == ESP_OK && valid_warn(v, s_cfg.cutoff_percent)) {
            s_cfg.warn_percent = v;
        }
        nvs_close(h);
    } else if (err != ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGW(TAG, "nvs_open read failed, using defaults: %s", esp_err_to_name(err));
    }

    s_loaded = true;
    return ESP_OK;
}

uint8_t battery_config_get_cell_count(void) {
    if (!s_loaded) battery_config_init();
    return s_cfg.cell_count;
}

uint8_t battery_config_get_cutoff_percent(void) {
    if (!s_loaded) battery_config_init();
    return s_cfg.cutoff_percent;
}

uint8_t battery_config_get_warn_percent(void) {
    if (!s_loaded) battery_config_init();
    return s_cfg.warn_percent;
}

esp_err_t battery_config_set_cell_count(uint8_t cells) {
    if (!valid_cells(cells)) return ESP_ERR_INVALID_ARG;
    if (!s_loaded) battery_config_init();
    s_cfg.cell_count = cells;
    return save_all();
}

esp_err_t battery_config_set_cutoff_percent(uint8_t percent) {
    if (!s_loaded) battery_config_init();
    if (!valid_cutoff(percent) || !valid_warn(s_cfg.warn_percent, percent)) return ESP_ERR_INVALID_ARG;
    s_cfg.cutoff_percent = percent;
    return save_all();
}

esp_err_t battery_config_set_warn_percent(uint8_t percent) {
    if (!s_loaded) battery_config_init();
    if (!valid_warn(percent, s_cfg.cutoff_percent)) return ESP_ERR_INVALID_ARG;
    s_cfg.warn_percent = percent;
    return save_all();
}

esp_err_t battery_config_commit(void) {
    if (!s_loaded) battery_config_init();
    return save_all();
}

int battery_config_to_json(char *out_buf, size_t out_buf_len) {
    if (!out_buf || out_buf_len == 0) return -1;
    if (!s_loaded) battery_config_init();
    int n = snprintf(out_buf, out_buf_len,
        "{\"cell_count\":%u,\"cutoff_percent\":%u,\"warn_percent\":%u}",
        (unsigned)s_cfg.cell_count,
        (unsigned)s_cfg.cutoff_percent,
        (unsigned)s_cfg.warn_percent);
    if (n < 0 || (size_t)n >= out_buf_len) {
        if (out_buf_len) out_buf[0] = '\0';
        return -1;
    }
    return n;
}

static bool parse_json_uint(const char *json, const char *key, long *out) {
    const char *p = strstr(json, key);
    if (!p) return false;
    p += strlen(key);
    while (*p && *p != ':') p++;
    if (*p != ':') return false;
    p++;
    while (*p && isspace((unsigned char)*p)) p++;
    char *end = NULL;
    long v = strtol(p, &end, 10);
    if (end == p) return false;
    *out = v;
    return true;
}

esp_err_t battery_config_apply_json_patch(const char *json_patch) {
    if (!json_patch) return ESP_ERR_INVALID_ARG;
    if (!s_loaded) battery_config_init();

    battery_config_t next = s_cfg;
    long v = 0;
    bool touched = false;

    if (parse_json_uint(json_patch, "\"cell_count\"", &v)) {
        if (v < BC_CELL_COUNT_MIN || v > BC_CELL_COUNT_MAX) return ESP_ERR_INVALID_ARG;
        next.cell_count = (uint8_t)v;
        touched = true;
    }
    if (parse_json_uint(json_patch, "\"cutoff_percent\"", &v)) {
        if (v < BC_CUTOFF_PERCENT_MIN || v > BC_CUTOFF_PERCENT_MAX) return ESP_ERR_INVALID_ARG;
        next.cutoff_percent = (uint8_t)v;
        touched = true;
    }
    if (parse_json_uint(json_patch, "\"warn_percent\"", &v)) {
        if (v < BC_WARN_PERCENT_MIN || v > BC_WARN_PERCENT_MAX) return ESP_ERR_INVALID_ARG;
        next.warn_percent = (uint8_t)v;
        touched = true;
    }
    if (!valid_warn(next.warn_percent, next.cutoff_percent)) return ESP_ERR_INVALID_ARG;

    if (!touched) return ESP_ERR_INVALID_ARG;
    s_cfg = next;
    return save_all();
}
