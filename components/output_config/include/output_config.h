// output_config.h — Per-output configuration stored in NVS
//
// Persists runtime-tunable output behavior (drive direction flips,
// servo uni/bi-direction, input-source mapping) across reboots so
// the web UI can offer a full setup experience without reflashing.
//
// Physical pin assignments are NOT stored here — those come from
// board_config.h at compile time. The schema below maps *logical*
// outputs (M1, M2, S1, S2) onto the physical pins, so the
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
    OC_OUT_S1      = 2,    // Servo / auxiliary channel 1
    OC_OUT_S2      = 3,    // Servo / auxiliary channel 2
    OC_OUT__COUNT  = 4,
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

// Legacy drive mixer mode. Kept for JSON/API compatibility; new runtime
// code uses oc_drive_setup_t below.
typedef enum {
    OC_DRIVE_TANK_SPLIT   = 0,    // left Y = left side, right Y = right side
    OC_DRIVE_ARCADE_LEFT  = 1,    // left Y throttle, left X turn
    OC_DRIVE_ARCADE_RIGHT = 2,    // right Y throttle, right X turn
    OC_DRIVE_ARCADE_SPLIT = 3,    // left Y throttle, right X turn
    OC_DRIVE__COUNT       = 4,
} oc_drive_mode_t;

typedef enum {
    OC_DRIVE_LAYOUT_DIFFERENTIAL = 0,
    OC_DRIVE_LAYOUT_SERVO_STEERING = 1,
    OC_DRIVE_LAYOUT__COUNT = 2,
} oc_drive_layout_t;

typedef enum {
    OC_DRIVE_METHOD_NONE = 0,
    OC_DRIVE_METHOD_TANK = 1,
    OC_DRIVE_METHOD_ARCADE = 2,
    OC_DRIVE_METHOD_SERVO_STEERING = 3,
    OC_DRIVE_METHOD__COUNT = 4,
} oc_drive_method_t;

typedef enum {
    OC_DRIVE_AXIS_NONE = 0,
    OC_DRIVE_AXIS_LY = 1,
    OC_DRIVE_AXIS_RY = 2,
    OC_DRIVE_AXIS_LX = 3,
    OC_DRIVE_AXIS_RX = 4,
    OC_DRIVE_AXIS_RT_MINUS_LT = 5,
    OC_DRIVE_AXIS_LT_MINUS_RT = 6,
    OC_DRIVE_AXIS_RT_ONLY = 7,
    OC_DRIVE_AXIS_LT_ONLY = 8,
    OC_DRIVE_AXIS_DPAD_Y = 9,
    OC_DRIVE_AXIS_DPAD_X = 10,
    OC_DRIVE_AXIS__COUNT = 11,
} oc_drive_axis_t;


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
    OC_SRC_LY         = 2,    // left stick Y (left drive forward/back)
    OC_SRC_RX         = 3,    // right stick X (turn)
    OC_SRC_RY         = 4,    // right stick Y (right drive forward/back)
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

typedef struct {
    oc_drive_layout_t layout;
    oc_drive_method_t method;
    oc_drive_axis_t left_axis;
    oc_drive_axis_t right_axis;
    oc_drive_axis_t throttle_axis;
    oc_drive_axis_t steering_axis;
    oc_output_id_t drive_motor_output;
    oc_output_id_t steering_output;
    oc_source_id_t precision_source;
    uint8_t precision_scale_pct;
    bool precision_latching; // false = active while held; true = toggle on press
    // Per-side drivetrain calibration. 100 = unchanged; lower slows that side.
    uint8_t left_speed_pct;
    uint8_t right_speed_pct;
    oc_source_id_t brake_source;
    oc_source_id_t invert_steering_source;
} oc_drive_setup_t;

typedef enum {
    OC_MOTOR_MODE_PROPORTIONAL = 0,
    OC_MOTOR_MODE_MOMENTARY = 1,
    OC_MOTOR_MODE_LATCHING = 2,
    OC_MOTOR_MODE_DISABLED = 3,
    OC_MOTOR_MODE__COUNT = 4,
} oc_motor_mode_t;

typedef enum {
    OC_PURPOSE_DISABLED       = 0,
    OC_PURPOSE_DRIVE          = 1,
    OC_PURPOSE_SERVO          = 2,
    OC_PURPOSE_ESC            = 3,
    OC_PURPOSE_DIGITAL_OUTPUT = 4,
    OC_PURPOSE_DIGITAL_INPUT  = 5,
    OC_PURPOSE_PWM_ACCESSORY  = 6,
    OC_PURPOSE_RGB_LIGHTING   = 7,
    OC_PURPOSE__COUNT         = 8,
} oc_purpose_t;

typedef enum {
    OC_PROTO_NONE              = 0,
    OC_PROTO_RC_SERVO_PWM      = 1,  // 50 Hz default
    OC_PROTO_RC_SERVO_PPM      = 2,  // 50 Hz default
    OC_PROTO_RC_ESC_PWM        = 3,  // 50 Hz default
    OC_PROTO_ONESHOT125        = 4,
    OC_PROTO_ONESHOT42         = 5,
    OC_PROTO_MULTISHOT         = 6,
    OC_PROTO_RC_SERVO_PWM_100  = 7,
    OC_PROTO_RC_SERVO_PWM_200  = 8,
    OC_PROTO_RC_SERVO_PWM_333  = 9,
    OC_PROTO_RC_ESC_PWM_100    = 10,
    OC_PROTO_RC_ESC_PWM_250    = 11,
    OC_PROTO_RC_ESC_PWM_333    = 12,
    OC_PROTO_RC_ESC_PWM_490    = 13,
    OC_PROTO_ONESHOT           = 14,
    OC_PROTO_GPIO              = 15,
    OC_PROTO_PWM_DUTY          = 16,
    OC_PROTO_RGB               = 17,
    OC_PROTO_RGBW              = 18,
    OC_PROTO__COUNT            = 19,
} oc_protocol_t;

typedef enum {
    OC_SEM_NONE              = 0,
    OC_SEM_POSITION_SERVO    = 1,
    OC_SEM_ESC_FORWARD_ONLY  = 2,
    OC_SEM_ESC_BIDIRECTIONAL = 3,
    OC_SEM_DIGITAL_OUTPUT    = 4,
    OC_SEM_DIGITAL_INPUT     = 5,
    OC_SEM_PWM_ACCESSORY     = 6,
    OC_SEM_RGB_LIGHTING      = 7,
    OC_SEM__COUNT            = 8,
} oc_semantics_t;

typedef enum {
    OC_RGB_PATTERN_SOLID = 0,
    OC_RGB_PATTERN_BLINK = 1,
    OC_RGB_PATTERN_BREATHE = 2,
    OC_RGB_PATTERN_RAINBOW = 3,
    OC_RGB_PATTERN_CHASE = 4,
    OC_RGB_PATTERN_BATTERY = 5,
    OC_RGB_PATTERN_CONTROLLER = 6,
    OC_RGB_PATTERN__COUNT = 7,
} oc_rgb_pattern_t;

typedef enum {
    OC_FAILSAFE_SAFE_STATE = 0,
    OC_FAILSAFE_HOLD_LAST  = 1,
} oc_failsafe_t;

typedef enum {
    OC_POWER_DEFAULT = 0,
    OC_POWER_ALLOW   = 1,
    OC_POWER_DISABLE = 2,
    OC_POWER_REDUCE  = 3,
} oc_power_override_t;

typedef enum {
    OC_SW1_ACTION_NONE = 0,
    OC_SW1_ACTION_PAIRING = 1,
    OC_SW1_ACTION_CLEAR_PAIR = 2,
    OC_SW1_ACTION_CANCEL_PAIRING = 3,
    OC_SW1_ACTION_RESET_OUTPUTS = 4,
    OC_SW1_ACTION_BATTERY_STATUS = 5,
    OC_SW1_ACTION__COUNT = 6,
} oc_sw1_action_t;

typedef struct {
    oc_sw1_action_t short_action;
    oc_sw1_action_t double_action;
    oc_sw1_action_t hold_action;
    uint16_t hold_ms;
} oc_sw1_config_t;

typedef enum {
    OC_WEAPON_ARMING_AND_DEADMAN = 0,
    OC_WEAPON_DEADMAN_ONLY       = 1,
    OC_WEAPON_BENCH_OVERRIDE     = 2,
} oc_weapon_safety_mode_t;

typedef enum {
    OC_ESC_ARM_MANUAL = 0,
    OC_ESC_ARM_BOOT = 1,
    OC_ESC_ARM_HOLD_SOURCE = 2,
    OC_ESC_ARM__COUNT = 3,
} oc_esc_arm_mode_t;

typedef enum {
    OC_DIGITAL_MODE_DIRECT       = 0,
    OC_DIGITAL_MODE_ANALOG_ABOVE = 1,
    OC_DIGITAL_MODE_ANALOG_BELOW = 2,
    OC_DIGITAL_MODE__COUNT       = 3,
} oc_digital_mode_t;

typedef enum {
    OC_DIGITAL_PRESET_DIRECT              = 0,
    OC_DIGITAL_PRESET_TRIGGER_LIGHT       = 1,
    OC_DIGITAL_PRESET_TRIGGER_HALF        = 2,
    OC_DIGITAL_PRESET_TRIGGER_FIRM        = 3,
    OC_DIGITAL_PRESET_STICK_ABOVE         = 4,
    OC_DIGITAL_PRESET_STICK_STRONG_ABOVE  = 5,
    OC_DIGITAL_PRESET_STICK_BELOW         = 6,
    OC_DIGITAL_PRESET_STICK_STRONG_BELOW  = 7,
    OC_DIGITAL_PRESET_CUSTOM              = 8,
    OC_DIGITAL_PRESET__COUNT              = 9,
} oc_digital_preset_t;

#define OC_DISPLAY_NAME_MAX_LEN 16

typedef enum { OC_RAMP_LINEAR = 0, OC_RAMP_S_CURVE } oc_ramp_curve_t;

// Per-output config blob. Defaults are filled in at boot via
// output_config_reset_defaults() so unknown NVS state still yields
// a usable robot.
typedef struct {
    oc_direction_t  direction;     // OC_DIR_NORMAL / REVERSED
    oc_servo_mode_t servo_mode;    // OC_SERVO_BI / UNI (servos only)
    uint8_t         deadzone_pct;  // 0..50; percent of stick range to ignore
    oc_source_id_t  primary;       // Source for forward-or-on direction
    oc_source_id_t  secondary;     // Source for reverse-or-off (motors/UNI servos)
    oc_motor_mode_t motor_mode;    // M1/M2 manual-output behavior when drive method is none

    char            display_name[OC_DISPLAY_NAME_MAX_LEN + 1];
    oc_purpose_t    purpose;
    oc_protocol_t   protocol;
    oc_semantics_t  semantics;
    uint16_t        min_pulse_us;
    uint16_t        center_pulse_us;
    uint16_t        max_pulse_us;
    uint16_t        frame_hz;
    uint8_t         neutral_deadzone_pct;
    bool            weapon_safety;
    oc_failsafe_t   failsafe;
    oc_weapon_safety_mode_t weapon_mode;
    oc_source_id_t  arming_source;
    oc_source_id_t  deadman_source;
    uint16_t        ramp_ms;         // acceleration time, 0 = instant
    uint16_t        deceleration_ms; // deceleration time, 0 = instant
    oc_ramp_curve_t ramp_curve;
    uint8_t         ramp_smoothing_pct; // 0..100 blend from linear to smoothstep
    oc_esc_arm_mode_t esc_arm_mode;
    oc_source_id_t  esc_arm_source;
    uint16_t        esc_arm_hold_ms;
    uint16_t        esc_arm_low_us;
    uint16_t        esc_arm_high_us;
    uint16_t        esc_arm_low_ms;
    uint16_t        esc_arm_high_ms;
    uint16_t        esc_arm_final_low_ms;
    oc_power_override_t power_good;
    oc_power_override_t power_warn;
    oc_power_override_t power_low;
    bool            active_high;
    bool            default_state;
    oc_digital_mode_t digital_mode;
    oc_digital_preset_t digital_preset;
    int16_t         digital_on_threshold;
    int16_t         digital_off_threshold;
    uint8_t         digital_custom_pct;
    uint16_t        pwm_frequency_hz;
    uint8_t         pwm_duty_pct;
    oc_rgb_pattern_t rgb_pattern;
    uint8_t         rgb_r;
    uint8_t         rgb_g;
    uint8_t         rgb_b;
    uint8_t         rgb_w;
    uint8_t         rgb_brightness_pct;
    uint16_t        rgb_led_count;
} oc_output_cfg_t;

// Wire format (JSON) sent to and received from the web UI. The C
// struct keeps the integers small; the JSON encoder expands them to
// readable keys. Keeping this struct on the C side means we don't
// need ArduinoJson on the device just for a 5-output config.

#define OC_NVS_NAMESPACE        "output_cfg"
#define OC_NVS_KEY_BLOB         "cfg_v1"
#define OC_NVS_KEY_DRIVE_MODE   "drive_v1"
#define OC_NVS_KEY_DRIVE_SETUP  "drive_setup_v1"
// Runtime cap on paired BLE controllers (1..BLE_MAX_PAIRED_CONTROLLERS).
// Defaults to 1 (Kevin's "one controller at a time" model); the upper
// bound matches the BLE array size. Stored as its own small key so old
// cfg_v1 blobs remain valid.
#define OC_NVS_KEY_MAX_PAIRED   "max_paired_v1"
#define OC_NVS_KEY_SW1_CONFIG   "sw1_cfg_v1"
#define OC_NVS_KEY_DISCONNECT_FAILSAFE "disc_fs_v1"
#define OC_MAX_PAIRED_DEFAULT   1
#define OC_MAX_PAIRED_CAP       4

// JSON output buffer sizing. Config is larger under schema v2 because each
// output includes purpose/protocol/calibration/safety/power metadata. 4KB
// covers the full config and source-list JSON with headroom on ESP32-C3.
#define OC_JSON_BUF_SIZE        6144
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

// Drive setup. Legacy drive_mode is still exposed for old clients, but
// runtime should read output_config_get_drive_setup().
oc_drive_mode_t output_config_get_drive_mode(void);
esp_err_t output_config_set_drive_mode(oc_drive_mode_t mode);
const char *output_config_drive_mode_name(oc_drive_mode_t mode);
bool output_config_drive_mode_from_str(const char *s, oc_drive_mode_t *out);
const oc_drive_setup_t *output_config_get_drive_setup(void);
esp_err_t output_config_set_drive_setup(const oc_drive_setup_t *setup);
const char *output_config_drive_layout_name(oc_drive_layout_t layout);
const char *output_config_drive_method_name(oc_drive_method_t method);
const char *output_config_drive_axis_name(oc_drive_axis_t axis);
bool output_config_drive_layout_from_str(const char *s, oc_drive_layout_t *out);
bool output_config_drive_method_from_str(const char *s, oc_drive_method_t *out);
bool output_config_drive_axis_from_str(const char *s, oc_drive_axis_t *out);

// Runtime cap on the BLE whitelist (1..OC_MAX_PAIRED_CAP). Default
// OC_MAX_PAIRED_DEFAULT when NVS is missing/invalid. Mirrored into the
// BLE subsystem on first ble_gamepad_set_max_paired() call (typically
// from web_config after output_config_init()).
uint8_t output_config_get_max_paired(void);
esp_err_t output_config_set_max_paired(uint8_t n);
const oc_sw1_config_t *output_config_get_sw1_config(void);
esp_err_t output_config_set_sw1_config(const oc_sw1_config_t *cfg);
const char *output_config_sw1_action_name(oc_sw1_action_t action);
bool output_config_sw1_action_from_str(const char *s, oc_sw1_action_t *out);
bool output_config_get_disconnect_failsafe_hold_last(void);
esp_err_t output_config_set_disconnect_failsafe_hold_last(bool hold_last);

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
//     "S1": {"purpose":"esc","protocol":"oneshot125","weapon_safety":true,"primary":"RT"} }
// The obsolete top-level "Weapon" key is rejected; other unknown top-level keys are ignored.
// Invalid values for a known key
// are rejected without modifying other fields. Returns ESP_OK on full
// success, ESP_ERR_INVALID_ARG on a parse/validation failure.
esp_err_t output_config_apply_json_patch(const char *json_patch);

// Human-readable label for a source id. Returned pointers are
// statically allocated; do not free.
const char *output_config_source_name(oc_source_id_t id);

// Reverse of output_config_source_name: parse "LX", "RT", "BTN_A", etc.
// into the enum. Returns true on success and writes the result to *out.
bool output_config_source_from_str(const char *s, oc_source_id_t *out);

// Stable string id used in JSON ("M1", "S1", etc).
const char *output_config_output_id_str(oc_output_id_t id);

// Resolve per-channel battery power policy for runtime gating. Returns
// true when the channel should remain active for the current battery state.
// Per-channel overrides win over purpose defaults. OC_POWER_REDUCE remains
// active and is exposed via output_config_channel_power_action() so runtime
// code can scale supported outputs.
bool output_config_channel_allowed(oc_output_id_t id, uint8_t battery_state);
oc_power_override_t output_config_channel_power_action(oc_output_id_t id, uint8_t battery_state);

#ifdef __cplusplus
}
#endif
