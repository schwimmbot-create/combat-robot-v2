// output_config.h — Per-output configuration stored in NVS
//
// Persists runtime-tunable output behavior (drive direction flips,
// servo uni/bi-direction, input-source mapping) across reboots so
// the web UI can offer a full setup experience without reflashing.
//
// Physical pin assignments are NOT stored here — those come from
// board_config.h at compile time. The schema below maps *logical*
// outputs (M1, M2, Weapon, S1, S2) onto the physical pins, so the
// web UI can present "Motor 1 direction" rather than "GPIO 0".
//
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

// Logical output identifiers. Order is stable; the IDs appear in
// /api/config JSON in this order. New IDs only add to the end so
// older clients can still parse the array.
typedef enum {
    OC_OUT_M1      = 0,    // Drive motor 1 (left wheel pair)
    OC_OUT_M2      = 1,    // Drive motor 2 (right wheel pair)
    OC_OUT_WEAPON  = 2,    // Weapon / ESC / drum
    OC_OUT_S1      = 3,    // Servo 1
    OC_OUT_S2      = 4,    // Servo 2
    OC_OUT__COUNT  = 5,
} oc_output_id_t;

// Motor direction. UI toggle flips this; the motor driver code
// reads it on next loop iteration.
typedef enum {
    OC_DIR_NORMAL  = 0,
    OC_DIR_REVERSED = 1,
} oc_direction_t;

// Servo mode. UNI means the servo only swings one way (0..100%);
// BI means it can swing both ways around a center (centers at 1500us
// in standard servo PWM).
typedef enum {
    OC_SERVO_BI   = 0,
    OC_SERVO_UNI  = 1,
} oc_servo_mode_t;

// Available controller input sources the UI can choose from. This
// list intentionally matches the standard HID gamepad report layout
// described in the project's esp32-ble-gamepad-integration skill:
//   Byte 0..3   : LX, LY, RX, RY (sticks)
//   Byte 4..5   : buttons (16-bit, low/high)
//   Byte 6..7   : LT, RT (triggers, 0..255)
//   Byte 8      : hat/dpad (0..7 = directions, 8 or 15 = center)
//
// Buttons come pre-decoded into named entries so the UI can present
// "A button", "R1", "Dpad Up" rather than bit offsets.
typedef enum {
    OC_SRC_NONE       = 0,
    OC_SRC_LX         = 1,    // left stick X (raw -512..511)
    OC_SRC_LY         = 2,    // left stick Y (forward/back on M1/M2)
    OC_SRC_RX         = 3,    // right stick X (turn)
    OC_SRC_RY         = 4,    // right stick Y (forward/back weapon)
    OC_SRC_LT         = 5,    // left trigger  (0..1023)
    OC_SRC_RT         = 6,    // right trigger (weapon)
    OC_SRC_BTN_A      = 7,
    OC_SRC_BTN_B      = 8,
    OC_SRC_BTN_X      = 9,
    OC_SRC_BTN_Y      = 10,
    OC_SRC_BTN_L1     = 11,
    OC_SRC_BTN_R1     = 12,
    OC_SRC_BTN_L2     = 13,
    OC_SRC_BTN_R2     = 14,
    OC_SRC_BTN_SELECT = 15,
    OC_SRC_BTN_START  = 16,
    OC_SRC_BTN_L3     = 17,
    OC_SRC_BTN_R3     = 18,
    OC_SRC_BTN_HOME   = 19,
    OC_SRC_DPAD_UP    = 20,
    OC_SRC_DPAD_DOWN  = 21,
    OC_SRC_DPAD_LEFT  = 22,
    OC_SRC_DPAD_RIGHT = 23,
    OC_SRC__COUNT     = 24,
} oc_source_id_t;

// Per-output config blob. Defaults are filled in at boot via
// output_config_reset_defaults() so unknown NVS state still yields
// a usable robot.
typedef struct {
    oc_direction_t  direction;     // OC_DIR_NORMAL / REVERSED
    oc_servo_mode_t servo_mode;    // OC_SERVO_BI / UNI (servos only)
    uint8_t         deadzone_pct;  // 0..50; percent of stick range to ignore
    oc_source_id_t  primary;       // Source for forward-or-on direction
    oc_source_id_t  secondary;     // Source for reverse-or-off (motos/UNI servos)
} oc_output_cfg_t;

// Wire format (JSON) sent to and received from the web UI. The C
// struct keeps the integers small; the JSON encoder expands them to
// readable keys. Keeping this struct on the C side means we don't
// need ArduinoJson on the device just for a 5-output config.

#define OC_NVS_NAMESPACE        "output_cfg"
#define OC_NVS_KEY_BLOB         "cfg_v1"

// JSON output buffer sizing. Config is ~700 bytes; source-list JSON is
// larger because it includes 24 id/name/label entries. 2KB covers both
// with headroom while staying small for ESP32-C3 RAM.
#define OC_JSON_BUF_SIZE        2048
#define OC_SOURCE_NAME_MAX_LEN  12

// Lifecycle ----------------------------------------------------------------

// Initialize the output_config subsystem. Loads persisted config from
// NVS into the runtime cache; falls back to defaults on first boot or
// if the stored blob is invalid.
esp_err_t output_config_init(void);

// Reset all outputs to defaults (no NVS write). Used by the "Reset
// to defaults" button on the web UI.
void output_config_reset_defaults(void);

// Read the in-RAM config for a single output. Out-of-range ids return
// the M1 defaults.
const oc_output_cfg_t *output_config_get(oc_output_id_t id);

// Per-output mutable setters. Each writes through to NVS atomically;
// the next reboot will see the change. Returns ESP_OK on success.
esp_err_t output_config_set_direction(oc_output_id_t id, oc_direction_t d);
esp_err_t output_config_set_servo_mode(oc_output_id_t id, oc_servo_mode_t m);
esp_err_t output_config_set_deadzone(oc_output_id_t id, uint8_t deadzone_pct);
esp_err_t output_config_set_source(oc_output_id_t id,
                                   oc_source_id_t primary,
                                   oc_source_id_t secondary);

// Commit current in-RAM state to NVS. Setters already commit; this
// is mostly for the "Reset + save defaults" workflow to be explicit.
esp_err_t output_config_commit(void);

// JSON serialization helpers ------------------------------------------------

// Render the full config (all 5 outputs + their source lists) as a
// JSON object suitable for serving at /api/config. The string is
// written into out_buf (size out_buf_len) and is always NUL-terminated.
// Returns the number of bytes written (excluding NUL), or -1 if
// out_buf is too small.
int output_config_to_json(char *out_buf, size_t out_buf_len);

// Render just the available input source list as a JSON array, used
// to populate <select> dropdowns in the UI. Same semantics.
int output_config_sources_to_json(char *out_buf, size_t out_buf_len);

// Apply a partial JSON patch to the in-RAM + NVS state. Accepted
// patch shape:
//   { "M1": {"direction":"reversed","deadzone":15},
//     "Weapon": {"primary":"RT","secondary":"LT"} }
// Unknown top-level keys are ignored; invalid values for a known key
// are rejected without modifying other fields. Returns ESP_OK on full
// success, ESP_ERR_INVALID_ARG on a parse/validation failure.
esp_err_t output_config_apply_json_patch(const char *json_patch);

// Human-readable label for a source id. Returned pointers are
// statically allocated; do not free.
const char *output_config_source_name(oc_source_id_t id);

// Stable string id used in JSON ("M1", "Weapon", etc).
const char *output_config_output_id_str(oc_output_id_t id);

#ifdef __cplusplus
}
#endif
