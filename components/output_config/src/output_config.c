// output_config.c — Per-output configuration storage + JSON helpers
//
// Authoring rules for this file:
//   * C11, no Arduino.h. Must work when included from C++ code that
//     links against the Arduino runtime.
//   * Self-contained JSON encoder/decoder — no external deps. We
//     only need a small subset.
//   * NVS blob for atomic read/write of all 5 outputs. Schema is
//     versioned via the NVS key name; bumping the key on a breaking
//     change keeps us from misinterpreting older stored blobs.
//
// SPDX-License-Identifier: Apache-2.0

#include "output_config.h"

#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>

#include "nvs_flash.h"
#include "nvs.h"
#include "esp_log.h"

static const char *TAG = "output_config";

// ---- Static tables -------------------------------------------------------

static const char *const kOutputIdStrings[OC_OUT__COUNT] = {
    "M1", "M2", "Weapon", "S1", "S2",
};

static const char *const kOutputDisplayNames[OC_OUT__COUNT] = {
    "Drive Motor 1",
    "Drive Motor 2",
    "Weapon / ESC",
    "Servo 1",
    "Servo 2",
};

static const char *const kSourceNames[OC_SRC__COUNT] = {
    "NONE",
    "LX",   "LY",   "RX",   "RY",
    "LT",   "RT",
    "A",    "B",    "X",    "Y",
    "L1",   "R1",   "L2",   "R2",
    "SELECT", "START", "L3", "R3", "HOME",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
};

static const char *const kSourceDisplayNames[OC_SRC__COUNT] = {
    "(none)",
    "Left Stick X",   "Left Stick Y",      "Right Stick X",  "Right Stick Y",
    "Left Trigger",   "Right Trigger",
    "A Button",       "B Button",          "X Button",       "Y Button",
    "L1 Bumper",      "R1 Bumper",         "L2 (digital)",   "R2 (digital)",
    "Select / Share", "Start / Options",   "L3 (stick click)", "R3 (stick click)",
    "Home / PS",      "D-Pad Up",          "D-Pad Down",     "D-Pad Left",
    "D-Pad Right",
};

static const char *const kDriveModeNames[OC_DRIVE__COUNT] = {
    "tank_split",
    "arcade_left",
    "arcade_right",
    "arcade_split",
};

// ---- In-RAM state --------------------------------------------------------

// Defaults describe the current hard-coded tank-drive behavior:
//   M1: left stick Y, M2: right stick Y
//   Weapon: right trigger
//   S1/S2: unassigned
static const oc_output_cfg_t kDefaults[OC_OUT__COUNT] = {
    [OC_OUT_M1]     = { OC_DIR_NORMAL, OC_SERVO_BI,  10, OC_SRC_LY, OC_SRC_NONE },
    [OC_OUT_M2]     = { OC_DIR_NORMAL, OC_SERVO_BI,  10, OC_SRC_RY, OC_SRC_NONE },
    [OC_OUT_WEAPON] = { OC_DIR_NORMAL, OC_SERVO_BI,   5, OC_SRC_RT, OC_SRC_NONE },
    [OC_OUT_S1]     = { OC_DIR_NORMAL, OC_SERVO_BI,  10, OC_SRC_NONE, OC_SRC_NONE },
    [OC_OUT_S2]     = { OC_DIR_NORMAL, OC_SERVO_BI,  10, OC_SRC_NONE, OC_SRC_NONE },
};

static oc_output_cfg_t s_cfg[OC_OUT__COUNT];
static oc_drive_mode_t s_drive_mode = OC_DRIVE_TANK_SPLIT;
static bool s_loaded = false;

// ---- Small helpers -------------------------------------------------------

bool output_config_id_from_str(const char *s, oc_output_id_t *out);

static esp_err_t save_all(void) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(OC_NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }
    err = nvs_set_blob(h, OC_NVS_KEY_BLOB, s_cfg, sizeof(s_cfg));
    if (err == ESP_OK) err = nvs_set_u8(h, OC_NVS_KEY_DRIVE_MODE, (uint8_t)s_drive_mode);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_set/commit failed: %s", esp_err_to_name(err));
    }
    return err;
}

// Validate ranges. Returns true if a config blob is sane.
static bool cfg_blob_is_sane(const oc_output_cfg_t *cfg) {
    for (int i = 0; i < OC_OUT__COUNT; i++) {
        const oc_output_cfg_t *c = &cfg[i];
        if ((unsigned)c->direction > 1) return false;
        if ((unsigned)c->servo_mode > 1) return false;
        if (c->deadzone_pct > 50) return false;
        if ((unsigned)c->primary >= OC_SRC__COUNT) return false;
        if ((unsigned)c->secondary >= OC_SRC__COUNT) return false;
    }
    return true;
}

// ---- Lifecycle -----------------------------------------------------------

void output_config_reset_defaults(void) {
    memcpy(s_cfg, kDefaults, sizeof(s_cfg));
    s_drive_mode = OC_DRIVE_TANK_SPLIT;
}

esp_err_t output_config_init(void) {
    if (s_loaded) return ESP_OK;

    nvs_handle_t h;
    esp_err_t err = nvs_open(OC_NVS_NAMESPACE, NVS_READONLY, &h);
    bool loaded_from_nvs = false;
    if (err == ESP_OK) {
        size_t len = sizeof(s_cfg);
        err = nvs_get_blob(h, OC_NVS_KEY_BLOB, s_cfg, &len);
        nvs_close(h);
        if (err == ESP_OK) {
            if (len == sizeof(s_cfg) && cfg_blob_is_sane(s_cfg)) {
                loaded_from_nvs = true;
                ESP_LOGI(TAG, "loaded %u bytes of output config from NVS",
                         (unsigned)len);
            } else {
                ESP_LOGW(TAG, "stored config size=%u expected=%u, discarding",
                         (unsigned)len, (unsigned)sizeof(s_cfg));
            }
        } else if (err == ESP_ERR_NVS_NOT_FOUND) {
            ESP_LOGI(TAG, "no stored config; using defaults");
        } else {
            ESP_LOGE(TAG, "nvs_get_blob failed: %s", esp_err_to_name(err));
        }
    } else if (err == ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGI(TAG, "NVS namespace %s not found yet; using defaults",
                 OC_NVS_NAMESPACE);
    } else {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
    }

    if (!loaded_from_nvs) {
        output_config_reset_defaults();
    }

    // Drive mode is stored as its own small key so old cfg_v1 blobs remain
    // valid. Missing/invalid values fall back to split tank drive.
    s_drive_mode = OC_DRIVE_TANK_SPLIT;
    if (nvs_open(OC_NVS_NAMESPACE, NVS_READONLY, &h) == ESP_OK) {
        uint8_t mode = 0;
        esp_err_t mode_err = nvs_get_u8(h, OC_NVS_KEY_DRIVE_MODE, &mode);
        nvs_close(h);
        if (mode_err == ESP_OK && mode < OC_DRIVE__COUNT) {
            s_drive_mode = (oc_drive_mode_t)mode;
        }
    }
    s_loaded = true;
    return ESP_OK;
}

const oc_output_cfg_t *output_config_get(oc_output_id_t id) {
    if ((unsigned)id >= OC_OUT__COUNT) id = OC_OUT_M1;
    return &s_cfg[id];
}

// ---- Per-output setters --------------------------------------------------

esp_err_t output_config_set_direction(oc_output_id_t id, oc_direction_t d) {
    if ((unsigned)id >= OC_OUT__COUNT || (unsigned)d > 1) {
        return ESP_ERR_INVALID_ARG;
    }
    s_cfg[id].direction = d;
    return save_all();
}

esp_err_t output_config_set_servo_mode(oc_output_id_t id, oc_servo_mode_t m) {
    if ((unsigned)id >= OC_OUT__COUNT || (unsigned)m > 1) {
        return ESP_ERR_INVALID_ARG;
    }
    s_cfg[id].servo_mode = m;
    return save_all();
}

esp_err_t output_config_set_deadzone(oc_output_id_t id, uint8_t deadzone_pct) {
    if ((unsigned)id >= OC_OUT__COUNT || deadzone_pct > 50) {
        return ESP_ERR_INVALID_ARG;
    }
    s_cfg[id].deadzone_pct = deadzone_pct;
    return save_all();
}

esp_err_t output_config_set_source(oc_output_id_t id,
                                   oc_source_id_t primary,
                                   oc_source_id_t secondary) {
    if ((unsigned)id >= OC_OUT__COUNT ||
        (unsigned)primary >= OC_SRC__COUNT ||
        (unsigned)secondary >= OC_SRC__COUNT) {
        return ESP_ERR_INVALID_ARG;
    }
    s_cfg[id].primary = primary;
    s_cfg[id].secondary = secondary;
    return save_all();
}

oc_drive_mode_t output_config_get_drive_mode(void) {
    return s_drive_mode;
}

esp_err_t output_config_set_drive_mode(oc_drive_mode_t mode) {
    if ((unsigned)mode >= OC_DRIVE__COUNT) return ESP_ERR_INVALID_ARG;
    s_drive_mode = mode;
    return save_all();
}

const char *output_config_drive_mode_name(oc_drive_mode_t mode) {
    if ((unsigned)mode >= OC_DRIVE__COUNT) return "tank_split";
    return kDriveModeNames[mode];
}

bool output_config_drive_mode_from_str(const char *s, oc_drive_mode_t *out) {
    if (!s || !out) return false;
    for (int i = 0; i < OC_DRIVE__COUNT; i++) {
        if (strcasecmp(s, kDriveModeNames[i]) == 0) {
            *out = (oc_drive_mode_t)i;
            return true;
        }
    }
    return false;
}

esp_err_t output_config_commit(void) {
    return save_all();
}

// ---- Label helpers -------------------------------------------------------

const char *output_config_source_name(oc_source_id_t id) {
    if ((unsigned)id >= OC_SRC__COUNT) return "INVALID";
    return kSourceNames[id];
}

const char *output_config_output_id_str(oc_output_id_t id) {
    if ((unsigned)id >= OC_OUT__COUNT) return "INVALID";
    return kOutputIdStrings[id];
}

// ---- Tiny JSON writer (no deps) -----------------------------------------
//
// Hand-rolled because adding ArduinoJson for a 5-element config is
// overkill and pulls ~50KB of flash on the C3.
//
// Supported subset: objects with string OR string-array values, plus
// integer values. Strings are escaped for " and \. Numbers are emitted
// as %d for ints; callers bake the digits into a temp buffer.

// Append `src` to `buf` between `*used` and `cap`, escaping JSON
// metacharacters. Returns true on success, false on overflow.
static bool json_append_escaped(char *buf, size_t cap, size_t *used, const char *src) {
    if (!buf || !used) return false;
    if (*used + 1 >= cap) return false;
    buf[(*used)++] = '"';
    while (*src && *used + 2 < cap) {
        char c = *src++;
        if (c == '"' || c == '\\') {
            buf[(*used)++] = '\\';
            if (*used + 1 >= cap) return false;
        }
        buf[(*used)++] = c;
    }
    if (*used + 1 >= cap) return false;
    buf[(*used)++] = '"';
    return true;
}

static bool json_append_raw(char *buf, size_t cap, size_t *used, const char *src) {
    size_t len = strlen(src);
    if (*used + len >= cap) return false;
    memcpy(buf + *used, src, len);
    *used += len;
    return true;
}

static bool json_append_int(char *buf, size_t cap, size_t *used, int v) {
    char tmp[16];
    int n = snprintf(tmp, sizeof(tmp), "%d", v);
    if (n <= 0 || (size_t)n >= sizeof(tmp)) return false;
    if (*used + (size_t)n >= cap) return false;
    memcpy(buf + *used, tmp, (size_t)n);
    *used += (size_t)n;
    return true;
}

static bool json_append_quoted_token(char *buf, size_t cap, size_t *used, const char *tok) {
    return json_append_escaped(buf, cap, used, tok);
}

// ---- Render output config as JSON ---------------------------------------

int output_config_to_json(char *out_buf, size_t out_buf_len) {
    if (!out_buf || out_buf_len < 4) return -1;
    size_t used = 0;
    bool ok = true;

    ok &= json_append_raw(out_buf, out_buf_len, &used, "{\"drive_mode\":");
    ok &= json_append_quoted_token(out_buf, out_buf_len, &used, output_config_drive_mode_name(s_drive_mode));
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"outputs\":{");
    for (int i = 0; i < OC_OUT__COUNT && ok; i++) {
        if (i > 0) ok &= json_append_raw(out_buf, out_buf_len, &used, ",");
        const oc_output_cfg_t *c = &s_cfg[i];
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kOutputIdStrings[i]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ":{");
        ok &= json_append_raw(out_buf, out_buf_len, &used, "\"id\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, i);
        ok &= json_append_raw(out_buf, out_buf_len, &used,
                              ",\"display_name\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kOutputDisplayNames[i]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"direction\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used,
                                        c->direction == OC_DIR_REVERSED ? "reversed" : "normal");
        // Servo type is only meaningful for S1/S2; expose for all so the
        // UI can decide whether to render the control.
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"servo_mode\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used,
                                        c->servo_mode == OC_SERVO_UNI ? "uni" : "bi");
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"deadzone\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->deadzone_pct);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"primary\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used,
                                        kSourceNames[c->primary]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"secondary\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used,
                                        kSourceNames[c->secondary]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, "}");
    }
    ok &= json_append_raw(out_buf, out_buf_len, &used, "}}");
    if (!ok) return -1;
    if (used >= out_buf_len) return -1;
    out_buf[used] = '\0';
    return (int)used;
}

int output_config_sources_to_json(char *out_buf, size_t out_buf_len) {
    if (!out_buf || out_buf_len < 4) return -1;
    size_t used = 0;
    bool ok = json_append_raw(out_buf, out_buf_len, &used, "{\"sources\":[");
    for (int i = 0; i < OC_SRC__COUNT && ok; i++) {
        if (i > 0) ok &= json_append_raw(out_buf, out_buf_len, &used, ",");
        ok &= json_append_raw(out_buf, out_buf_len, &used, "{\"id\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, i);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"name\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kSourceNames[i]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"label\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kSourceDisplayNames[i]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, "}");
    }
    ok &= json_append_raw(out_buf, out_buf_len, &used, "]}");
    if (!ok) return -1;
    if (used >= out_buf_len) return -1;
    out_buf[used] = '\0';
    return (int)used;
}

// ---- Apply JSON patch ---------------------------------------------------

// Locate the value of a key in a flat JSON object. This is a tiny
// scanner, not a real parser; it accepts only the patch shape described
// in the header.

static const char *find_key(const char *json, const char *key) {
    char needle[64];
    int n = snprintf(needle, sizeof(needle), "\"%s\"", key);
    if (n <= 0 || (size_t)n >= sizeof(needle)) return NULL;
    return strstr(json, needle);
}

// Parse a string value at `cursor`, advancing it past the closing quote.
// On success writes up to dst_len bytes (NUL-terminated). Returns true.
static bool parse_bare_string_value(const char **cursor, char *dst, size_t dst_len) {
    const char *p = *cursor;
    while (*p && isspace((unsigned char)*p)) p++;
    if (*p != '"') return false;
    p++;
    size_t i = 0;
    while (*p && *p != '"') {
        if (*p == '\\' && p[1]) p++;
        if (i + 1 >= dst_len) return false;
        dst[i++] = *p++;
    }
    if (*p != '"') return false;
    dst[i] = '\0';
    *cursor = p + 1;
    return true;
}

static bool parse_string_value(const char **cursor, char *dst, size_t dst_len) {
    const char *p = *cursor;
    while (*p && isspace((unsigned char)*p)) p++;
    if (*p != ':') return false;
    p++;
    return parse_bare_string_value(&p, dst, dst_len) && (*cursor = p, true);
}

bool output_config_id_from_str(const char *s, oc_output_id_t *out) {
    for (int i = 0; i < OC_OUT__COUNT; i++) {
        if (strcmp(s, kOutputIdStrings[i]) == 0) {
            *out = (oc_output_id_t)i;
            return true;
        }
    }
    return false;
}

bool output_config_source_from_str(const char *s, oc_source_id_t *out) {
    if (!s) return false;
    // Accept both "RT" and "RT " etc.
    for (int i = 0; i < OC_SRC__COUNT; i++) {
        if (strcasecmp(s, kSourceNames[i]) == 0) {
            *out = (oc_source_id_t)i;
            return true;
        }
    }
    return false;
}

static bool apply_patch_one(oc_output_id_t id, const char *body) {
    bool dirty = false;
    const char *p = body;

    // leading '{'
    while (*p && isspace((unsigned char)*p)) p++;
    if (*p != '{') return false;
    p++;

    while (*p && *p != '}') {
        while (*p && isspace((unsigned char)*p)) p++;
        if (*p == '}') break;
        if (*p != '"') return false;

        // read key
        const char *key_start = ++p;
        while (*p && *p != '"') {
            if (*p == '\\' && p[1]) p++;
            p++;
        }
        if (*p != '"') return false;
        size_t klen = (size_t)(p - key_start);
        char key[24] = {0};
        if (klen >= sizeof(key)) return false;
        memcpy(key, key_start, klen);
        p++; // closing "

        if (strcmp(key, "deadzone") == 0) {
            while (*p && isspace((unsigned char)*p)) p++;
            if (*p != ':') return false;
            p++;
            while (*p && isspace((unsigned char)*p)) p++;
            char *end = NULL;
            long d = strtol(p, &end, 10);
            if (end == p || d < 0 || d > 50) return false;
            p = end;
            if (s_cfg[id].deadzone_pct != (uint8_t)d) { s_cfg[id].deadzone_pct = (uint8_t)d; dirty = true; }
        } else {
            char value[24] = {0};
            if (!parse_string_value(&p, value, sizeof(value))) return false;

            if (strcmp(key, "direction") == 0) {
                if (strcmp(value, "normal") == 0) {
                    if (s_cfg[id].direction != OC_DIR_NORMAL) { s_cfg[id].direction = OC_DIR_NORMAL; dirty = true; }
                } else if (strcmp(value, "reversed") == 0) {
                    if (s_cfg[id].direction != OC_DIR_REVERSED) { s_cfg[id].direction = OC_DIR_REVERSED; dirty = true; }
                } else return false;
            } else if (strcmp(key, "servo_mode") == 0) {
                if (strcmp(value, "bi") == 0) {
                    if (s_cfg[id].servo_mode != OC_SERVO_BI) { s_cfg[id].servo_mode = OC_SERVO_BI; dirty = true; }
                } else if (strcmp(value, "uni") == 0) {
                    if (s_cfg[id].servo_mode != OC_SERVO_UNI) { s_cfg[id].servo_mode = OC_SERVO_UNI; dirty = true; }
                } else return false;
            } else if (strcmp(key, "primary") == 0) {
                oc_source_id_t s;
                if (!output_config_source_from_str(value, &s)) return false;
                if (s_cfg[id].primary != s) { s_cfg[id].primary = s; dirty = true; }
            } else if (strcmp(key, "secondary") == 0) {
                oc_source_id_t s;
                if (!output_config_source_from_str(value, &s)) return false;
                if (s_cfg[id].secondary != s) { s_cfg[id].secondary = s; dirty = true; }
            } else {
                // Unknown string key: accept silently for forward-compat.
            }
        }

        while (*p && isspace((unsigned char)*p)) p++;
        if (*p == ',') p++;
    }
    return !dirty ? true : true; // dirty is informational; we always report apply ok
}

esp_err_t output_config_apply_json_patch(const char *json_patch) {
    if (!json_patch) return ESP_ERR_INVALID_ARG;

    // For each top-level key, find its object body and apply.
    const char *p = json_patch;
    while (*p && isspace((unsigned char)*p)) p++;
    if (*p != '{') return ESP_ERR_INVALID_ARG;
    p++;

    while (*p && *p != '}') {
        while (*p && isspace((unsigned char)*p)) p++;
        if (*p == '}') break;
        if (*p != '"') return ESP_ERR_INVALID_ARG;

        const char *key_start = ++p;
        while (*p && *p != '"') {
            if (*p == '\\' && p[1]) p++;
            p++;
        }
        if (*p != '"') return ESP_ERR_INVALID_ARG;
        size_t klen = (size_t)(p - key_start);
        char key[24] = {0};
        // sizeof(key) is 24; allow klen in [0, 23] so we always have room
        // for a NUL terminator at key[klen]. A klen of 24 would otherwise
        // write past the buffer (memcpy + later null-termination).
        if (klen >= sizeof(key) - 1) return ESP_ERR_INVALID_ARG;
        memcpy(key, key_start, klen);
        p++;

        // skip colon + whitespace
        while (*p && isspace((unsigned char)*p)) p++;
        if (*p != ':') return ESP_ERR_INVALID_ARG;
        p++;
        while (*p && isspace((unsigned char)*p)) p++;

        if (strcmp(key, "drive_mode") == 0) {
            char value[24] = {0};
            oc_drive_mode_t mode;
            if (!parse_bare_string_value(&p, value, sizeof(value))) return ESP_ERR_INVALID_ARG;
            if (!output_config_drive_mode_from_str(value, &mode)) return ESP_ERR_INVALID_ARG;
            s_drive_mode = mode;
            while (*p && isspace((unsigned char)*p)) p++;
            if (*p == ',') p++;
            continue;
        }

        // remember body start, find matching closing brace (simple depth count)
        if (*p != '{') return ESP_ERR_INVALID_ARG;
        const char *body = p;
        int depth = 0;
        while (*p) {
            if (*p == '{') depth++;
            else if (*p == '}') {
                depth--;
                if (depth == 0) { p++; break; }
            }
            p++;
        }
        if (depth != 0) return ESP_ERR_INVALID_ARG;

        oc_output_id_t id;
        if (output_config_id_from_str(key, &id)) {
            if (!apply_patch_one(id, body)) return ESP_ERR_INVALID_ARG;
        }
        // unknown output key: ignored (forward-compat)
        while (*p && isspace((unsigned char)*p)) p++;
        if (*p == ',') p++;
    }

    return save_all();
}
