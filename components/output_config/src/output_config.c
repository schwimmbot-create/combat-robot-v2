// output_config.c — Per-output configuration storage + JSON helpers
//
// Authoring rules for this file:
//   * C11, no Arduino.h. Must work when included from C++ code that
//     links against the Arduino runtime.
//   * Self-contained JSON encoder/decoder — no external deps. We
//     only need a small subset.
//   * NVS blob for atomic read/write of all 4 outputs. Schema is
//     versioned via the NVS key name; bumping the key on a breaking
//     change keeps us from misinterpreting older stored blobs.
//
// SPDX-License-Identifier: Apache-2.0

#include "output_config.h"

#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>
#include <errno.h>
#include <limits.h>

#include "nvs_flash.h"
#include "nvs.h"
#include "esp_log.h"

static const char *TAG = "output_config";

// ---- Static tables -------------------------------------------------------

static const char *const kOutputIdStrings[OC_OUT__COUNT] = {
    "M1", "M2", "S1", "S2",
};

static const char *const kOutputDisplayNames[OC_OUT__COUNT] = {
    "Drive Motor 1",
    "Drive Motor 2",
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

static const char *const kDriveLayoutNames[OC_DRIVE_LAYOUT__COUNT] = {
    "differential",
    "servo_steering",
};

static const char *const kDriveMethodNames[OC_DRIVE_METHOD__COUNT] = {
    "none",
    "tank",
    "arcade",
    "servo_steering",
};

static const char *const kDriveAxisNames[OC_DRIVE_AXIS__COUNT] = {
    "NONE",
    "LY",
    "RY",
    "LX",
    "RX",
    "RT_MINUS_LT",
    "LT_MINUS_RT",
    "RT_ONLY",
    "LT_ONLY",
    "DPAD_Y",
    "DPAD_X",
};

static const char *const kPurposeNames[OC_PURPOSE__COUNT] = {
    "disabled",
    "drive",
    "servo",
    "esc",
    "digital_output",
    "digital_input",
    "pwm_accessory",
};

static const char *const kProtocolNames[OC_PROTO__COUNT] = {
    "none",
    "rc_servo_pwm",
    "rc_servo_ppm",
    "rc_esc_pwm",
    "oneshot125",
    "oneshot42",
    "multishot",
    "rc_servo_pwm_100",
    "rc_servo_pwm_200",
    "rc_servo_pwm_333",
    "rc_esc_pwm_100",
    "rc_esc_pwm_250",
    "rc_esc_pwm_333",
    "rc_esc_pwm_490",
    "oneshot",
    "gpio",
    "pwm_duty",
};

static const char *const kSemanticsNames[OC_SEM__COUNT] = {
    "none",
    "position_servo",
    "esc_forward_only",
    "esc_bidirectional",
    "digital_output",
    "digital_input",
    "pwm_accessory",
};

static const char *const kFailsafeNames[] = {
    "safe_state",
    "hold_last",
};

static const char *const kWeaponModeNames[] = {
    "arming_and_deadman",
    "deadman_only",
    "bench_override",
};

static const char *const kPowerNames[] = {
    "default",
    "allow",
    "disable",
    "reduce",
};

static const char *const kEscArmModeNames[OC_ESC_ARM__COUNT] = {
    "manual",
    "boot",
    "hold_source",
};

static const char *const kDigitalModeNames[OC_DIGITAL_MODE__COUNT] = {
    "direct",
    "analog_above",
    "analog_below",
};

static const char *const kDigitalPresetNames[OC_DIGITAL_PRESET__COUNT] = {
    "direct",
    "trigger_light",
    "trigger_half",
    "trigger_firm",
    "stick_above",
    "stick_strong_above",
    "stick_below",
    "stick_strong_below",
    "custom",
};

static const char *const kMotorModeNames[OC_MOTOR_MODE__COUNT] = {
    "proportional",
    "momentary",
    "latching",
    "disabled",
};

// ---- In-RAM state --------------------------------------------------------

// Defaults describe the current hard-coded tank-drive behavior:
//   M1: left stick Y, M2: right stick Y
//   S1/S2: servo-capable auxiliary channels, unassigned by default
static const oc_output_cfg_t kDefaults[OC_OUT__COUNT] = {
    [OC_OUT_M1] = {
        .direction = OC_DIR_NORMAL, .servo_mode = OC_SERVO_BI, .deadzone_pct = 10,
        .primary = OC_SRC_LY, .secondary = OC_SRC_NONE, .motor_mode = OC_MOTOR_MODE_PROPORTIONAL,
        .display_name = "Motor 1", .purpose = OC_PURPOSE_DRIVE, .protocol = OC_PROTO_NONE,
        .semantics = OC_SEM_NONE, .min_pulse_us = 0, .center_pulse_us = 0, .max_pulse_us = 0,
        .frame_hz = 0, .neutral_deadzone_pct = 0, .weapon_safety = false,
        .failsafe = OC_FAILSAFE_SAFE_STATE, .weapon_mode = OC_WEAPON_ARMING_AND_DEADMAN,
        .arming_source = OC_SRC_NONE, .deadman_source = OC_SRC_NONE, .ramp_ms = 0,
        .esc_arm_mode = OC_ESC_ARM_MANUAL, .esc_arm_source = OC_SRC_NONE, .esc_arm_hold_ms = 2000,
        .esc_arm_low_us = 1000, .esc_arm_high_us = 2000, .esc_arm_low_ms = 1000,
        .esc_arm_high_ms = 1000, .esc_arm_final_low_ms = 1000,
        .power_good = OC_POWER_DEFAULT, .power_warn = OC_POWER_DEFAULT, .power_low = OC_POWER_DEFAULT,
        .active_high = true, .default_state = false, .digital_mode = OC_DIGITAL_MODE_DIRECT,
        .digital_preset = OC_DIGITAL_PRESET_DIRECT, .digital_on_threshold = 1, .digital_off_threshold = 0,
        .digital_custom_pct = 50, .pwm_frequency_hz = 20000, .pwm_duty_pct = 0,
    },
    [OC_OUT_M2] = {
        .direction = OC_DIR_NORMAL, .servo_mode = OC_SERVO_BI, .deadzone_pct = 10,
        .primary = OC_SRC_RY, .secondary = OC_SRC_NONE, .motor_mode = OC_MOTOR_MODE_PROPORTIONAL,
        .display_name = "Motor 2", .purpose = OC_PURPOSE_DRIVE, .protocol = OC_PROTO_NONE,
        .semantics = OC_SEM_NONE, .min_pulse_us = 0, .center_pulse_us = 0, .max_pulse_us = 0,
        .frame_hz = 0, .neutral_deadzone_pct = 0, .weapon_safety = false,
        .failsafe = OC_FAILSAFE_SAFE_STATE, .weapon_mode = OC_WEAPON_ARMING_AND_DEADMAN,
        .arming_source = OC_SRC_NONE, .deadman_source = OC_SRC_NONE, .ramp_ms = 0,
        .esc_arm_mode = OC_ESC_ARM_MANUAL, .esc_arm_source = OC_SRC_NONE, .esc_arm_hold_ms = 2000,
        .esc_arm_low_us = 1000, .esc_arm_high_us = 2000, .esc_arm_low_ms = 1000,
        .esc_arm_high_ms = 1000, .esc_arm_final_low_ms = 1000,
        .power_good = OC_POWER_DEFAULT, .power_warn = OC_POWER_DEFAULT, .power_low = OC_POWER_DEFAULT,
        .active_high = true, .default_state = false, .digital_mode = OC_DIGITAL_MODE_DIRECT,
        .digital_preset = OC_DIGITAL_PRESET_DIRECT, .digital_on_threshold = 1, .digital_off_threshold = 0,
        .digital_custom_pct = 50, .pwm_frequency_hz = 20000, .pwm_duty_pct = 0,
    },
    [OC_OUT_S1] = {
        .direction = OC_DIR_NORMAL, .servo_mode = OC_SERVO_BI, .deadzone_pct = 10,
        .primary = OC_SRC_NONE, .secondary = OC_SRC_NONE, .motor_mode = OC_MOTOR_MODE_DISABLED,
        .display_name = "Servo 1", .purpose = OC_PURPOSE_SERVO, .protocol = OC_PROTO_RC_SERVO_PWM,
        .semantics = OC_SEM_POSITION_SERVO, .min_pulse_us = 1000, .center_pulse_us = 1500, .max_pulse_us = 2000,
        .frame_hz = 50, .neutral_deadzone_pct = 5, .weapon_safety = false,
        .failsafe = OC_FAILSAFE_SAFE_STATE, .weapon_mode = OC_WEAPON_ARMING_AND_DEADMAN,
        .arming_source = OC_SRC_NONE, .deadman_source = OC_SRC_NONE, .ramp_ms = 0,
        .esc_arm_mode = OC_ESC_ARM_MANUAL, .esc_arm_source = OC_SRC_NONE, .esc_arm_hold_ms = 2000,
        .esc_arm_low_us = 1000, .esc_arm_high_us = 2000, .esc_arm_low_ms = 1000,
        .esc_arm_high_ms = 1000, .esc_arm_final_low_ms = 1000,
        .power_good = OC_POWER_DEFAULT, .power_warn = OC_POWER_DEFAULT, .power_low = OC_POWER_DEFAULT,
        .active_high = true, .default_state = false, .digital_mode = OC_DIGITAL_MODE_DIRECT,
        .digital_preset = OC_DIGITAL_PRESET_DIRECT, .digital_on_threshold = 1, .digital_off_threshold = 0,
        .digital_custom_pct = 50, .pwm_frequency_hz = 0, .pwm_duty_pct = 0,
    },
    [OC_OUT_S2] = {
        .direction = OC_DIR_NORMAL, .servo_mode = OC_SERVO_BI, .deadzone_pct = 10,
        .primary = OC_SRC_NONE, .secondary = OC_SRC_NONE, .motor_mode = OC_MOTOR_MODE_DISABLED,
        .display_name = "Servo 2", .purpose = OC_PURPOSE_SERVO, .protocol = OC_PROTO_RC_SERVO_PWM,
        .semantics = OC_SEM_POSITION_SERVO, .min_pulse_us = 1000, .center_pulse_us = 1500, .max_pulse_us = 2000,
        .frame_hz = 50, .neutral_deadzone_pct = 5, .weapon_safety = false,
        .failsafe = OC_FAILSAFE_SAFE_STATE, .weapon_mode = OC_WEAPON_ARMING_AND_DEADMAN,
        .arming_source = OC_SRC_NONE, .deadman_source = OC_SRC_NONE, .ramp_ms = 0,
        .esc_arm_mode = OC_ESC_ARM_MANUAL, .esc_arm_source = OC_SRC_NONE, .esc_arm_hold_ms = 2000,
        .esc_arm_low_us = 1000, .esc_arm_high_us = 2000, .esc_arm_low_ms = 1000,
        .esc_arm_high_ms = 1000, .esc_arm_final_low_ms = 1000,
        .power_good = OC_POWER_DEFAULT, .power_warn = OC_POWER_DEFAULT, .power_low = OC_POWER_DEFAULT,
        .active_high = true, .default_state = false, .digital_mode = OC_DIGITAL_MODE_DIRECT,
        .digital_preset = OC_DIGITAL_PRESET_DIRECT, .digital_on_threshold = 1, .digital_off_threshold = 0,
        .digital_custom_pct = 50, .pwm_frequency_hz = 0, .pwm_duty_pct = 0,
    },
};

static oc_output_cfg_t s_cfg[OC_OUT__COUNT];
static oc_drive_mode_t s_drive_mode = OC_DRIVE_TANK_SPLIT;
static oc_drive_setup_t s_drive_setup = {
    .layout = OC_DRIVE_LAYOUT_DIFFERENTIAL,
    .method = OC_DRIVE_METHOD_TANK,
    .left_axis = OC_DRIVE_AXIS_LY,
    .right_axis = OC_DRIVE_AXIS_RY,
    .throttle_axis = OC_DRIVE_AXIS_LY,
    .steering_axis = OC_DRIVE_AXIS_LX,
    .drive_motor_output = OC_OUT_M1,
    .steering_output = OC_OUT_S1,
    .precision_source = OC_SRC_NONE,
    .precision_scale_pct = 50,
    .brake_source = OC_SRC_NONE,
    .invert_steering_source = OC_SRC_NONE,
};
static uint8_t s_max_paired = OC_MAX_PAIRED_DEFAULT;
static bool s_loaded = false;

// ---- Small helpers -------------------------------------------------------

bool output_config_id_from_str(const char *s, oc_output_id_t *out);
static bool table_lookup(const char *s, const char *const *names, int count, int *out);

static bool drive_axis_is_valid_for_throttle(oc_drive_axis_t axis) {
    switch (axis) {
        case OC_DRIVE_AXIS_LY:
        case OC_DRIVE_AXIS_RY:
        case OC_DRIVE_AXIS_RT_MINUS_LT:
        case OC_DRIVE_AXIS_LT_MINUS_RT:
        case OC_DRIVE_AXIS_RT_ONLY:
        case OC_DRIVE_AXIS_LT_ONLY:
        case OC_DRIVE_AXIS_DPAD_Y:
            return true;
        default:
            return false;
    }
}

static bool drive_axis_is_valid_for_steering(oc_drive_axis_t axis) {
    return axis == OC_DRIVE_AXIS_LX || axis == OC_DRIVE_AXIS_RX || axis == OC_DRIVE_AXIS_DPAD_X;
}

static bool drive_setup_is_sane(const oc_drive_setup_t *setup) {
    if (!setup) return false;
    if ((unsigned)setup->layout >= OC_DRIVE_LAYOUT__COUNT) return false;
    if ((unsigned)setup->method >= OC_DRIVE_METHOD__COUNT) return false;
    if ((unsigned)setup->left_axis >= OC_DRIVE_AXIS__COUNT) return false;
    if ((unsigned)setup->right_axis >= OC_DRIVE_AXIS__COUNT) return false;
    if ((unsigned)setup->throttle_axis >= OC_DRIVE_AXIS__COUNT) return false;
    if ((unsigned)setup->steering_axis >= OC_DRIVE_AXIS__COUNT) return false;
    if ((unsigned)setup->drive_motor_output >= OC_OUT__COUNT) return false;
    if ((unsigned)setup->steering_output >= OC_OUT__COUNT) return false;
    if ((unsigned)setup->precision_source >= OC_SRC__COUNT) return false;
    if ((unsigned)setup->brake_source >= OC_SRC__COUNT) return false;
    if ((unsigned)setup->invert_steering_source >= OC_SRC__COUNT) return false;
    if (setup->precision_scale_pct > 100) return false;
    if (setup->method == OC_DRIVE_METHOD_NONE) return true;
    if (setup->layout == OC_DRIVE_LAYOUT_DIFFERENTIAL) {
        if (setup->method == OC_DRIVE_METHOD_TANK) {
            return drive_axis_is_valid_for_throttle(setup->left_axis) &&
                   drive_axis_is_valid_for_throttle(setup->right_axis);
        }
        if (setup->method == OC_DRIVE_METHOD_ARCADE) {
            return drive_axis_is_valid_for_throttle(setup->throttle_axis) &&
                   drive_axis_is_valid_for_steering(setup->steering_axis);
        }
        return false;
    }
    if (setup->layout == OC_DRIVE_LAYOUT_SERVO_STEERING) {
        return setup->method == OC_DRIVE_METHOD_SERVO_STEERING &&
               (setup->drive_motor_output == OC_OUT_M1 || setup->drive_motor_output == OC_OUT_M2) &&
               (setup->steering_output == OC_OUT_S1 || setup->steering_output == OC_OUT_S2) &&
               drive_axis_is_valid_for_throttle(setup->throttle_axis) &&
               drive_axis_is_valid_for_steering(setup->steering_axis);
    }
    return false;
}

static oc_drive_setup_t drive_setup_for_legacy_mode(oc_drive_mode_t mode) {
    oc_drive_setup_t setup = {
        .layout = OC_DRIVE_LAYOUT_DIFFERENTIAL,
        .method = OC_DRIVE_METHOD_TANK,
        .left_axis = OC_DRIVE_AXIS_LY,
        .right_axis = OC_DRIVE_AXIS_RY,
        .throttle_axis = OC_DRIVE_AXIS_LY,
        .steering_axis = OC_DRIVE_AXIS_LX,
        .drive_motor_output = OC_OUT_M1,
        .steering_output = OC_OUT_S1,
        .precision_source = OC_SRC_NONE,
        .precision_scale_pct = 50,
        .brake_source = OC_SRC_NONE,
        .invert_steering_source = OC_SRC_NONE,
    };
    switch (mode) {
        case OC_DRIVE_ARCADE_LEFT:
            setup.method = OC_DRIVE_METHOD_ARCADE;
            setup.throttle_axis = OC_DRIVE_AXIS_LY;
            setup.steering_axis = OC_DRIVE_AXIS_LX;
            break;
        case OC_DRIVE_ARCADE_RIGHT:
            setup.method = OC_DRIVE_METHOD_ARCADE;
            setup.throttle_axis = OC_DRIVE_AXIS_RY;
            setup.steering_axis = OC_DRIVE_AXIS_RX;
            break;
        case OC_DRIVE_ARCADE_SPLIT:
            setup.method = OC_DRIVE_METHOD_ARCADE;
            setup.throttle_axis = OC_DRIVE_AXIS_LY;
            setup.steering_axis = OC_DRIVE_AXIS_RX;
            break;
        case OC_DRIVE_TANK_SPLIT:
        default:
            break;
    }
    return setup;
}

static esp_err_t save_all(void) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(OC_NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open failed: %s", esp_err_to_name(err));
        return err;
    }
    err = nvs_set_blob(h, OC_NVS_KEY_BLOB, s_cfg, sizeof(s_cfg));
    if (err == ESP_OK) err = nvs_set_u8(h, OC_NVS_KEY_DRIVE_MODE, (uint8_t)s_drive_mode);
    if (err == ESP_OK) err = nvs_set_blob(h, OC_NVS_KEY_DRIVE_SETUP, &s_drive_setup, sizeof(s_drive_setup));
    if (err == ESP_OK) err = nvs_set_u8(h, OC_NVS_KEY_MAX_PAIRED, s_max_paired);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_set/commit failed: %s", esp_err_to_name(err));
    }
    return err;
}

// Validate ranges. Returns true if a config blob is sane.
static bool digital_thresholds_are_sane(const oc_output_cfg_t *c) {
    if ((unsigned)c->digital_mode >= OC_DIGITAL_MODE__COUNT) return false;
    if ((unsigned)c->digital_preset >= OC_DIGITAL_PRESET__COUNT) return false;
    if (c->digital_custom_pct > 100) return false;
    if (c->digital_on_threshold < -1024 || c->digital_on_threshold > 1024) return false;
    if (c->digital_off_threshold < -1024 || c->digital_off_threshold > 1024) return false;
    if (c->digital_mode == OC_DIGITAL_MODE_ANALOG_ABOVE &&
        !(c->digital_on_threshold > c->digital_off_threshold)) return false;
    if (c->digital_mode == OC_DIGITAL_MODE_ANALOG_BELOW &&
        !(c->digital_on_threshold < c->digital_off_threshold)) return false;
    return true;
}

static bool cfg_blob_is_sane(const oc_output_cfg_t *cfg) {
    for (int i = 0; i < OC_OUT__COUNT; i++) {
        const oc_output_cfg_t *c = &cfg[i];
        if ((unsigned)c->direction > 1) return false;
        if ((unsigned)c->servo_mode > 1) return false;
        if (c->deadzone_pct > 50) return false;
        if ((unsigned)c->primary >= OC_SRC__COUNT) return false;
        if ((unsigned)c->secondary >= OC_SRC__COUNT) return false;
        if ((unsigned)c->motor_mode >= OC_MOTOR_MODE__COUNT) return false;
        if (c->display_name[OC_DISPLAY_NAME_MAX_LEN] != '\0') return false;
        if ((unsigned)c->purpose >= OC_PURPOSE__COUNT) return false;
        if ((unsigned)c->protocol >= OC_PROTO__COUNT) return false;
        if ((unsigned)c->semantics >= OC_SEM__COUNT) return false;
        if ((unsigned)c->failsafe > OC_FAILSAFE_HOLD_LAST) return false;
        if ((unsigned)c->weapon_mode > OC_WEAPON_BENCH_OVERRIDE) return false;
        if ((unsigned)c->esc_arm_mode >= OC_ESC_ARM__COUNT) return false;
        if ((unsigned)c->arming_source >= OC_SRC__COUNT) return false;
        if ((unsigned)c->deadman_source >= OC_SRC__COUNT) return false;
        if ((unsigned)c->esc_arm_source >= OC_SRC__COUNT) return false;
        if ((unsigned)c->power_good > OC_POWER_REDUCE) return false;
        if ((unsigned)c->power_warn > OC_POWER_REDUCE) return false;
        if ((unsigned)c->power_low > OC_POWER_REDUCE) return false;
        if (c->neutral_deadzone_pct > 50) return false;
        if (!digital_thresholds_are_sane(c)) return false;
        if ((i == OC_OUT_M1 || i == OC_OUT_M2) &&
            (c->purpose != OC_PURPOSE_DRIVE || c->protocol != OC_PROTO_NONE)) return false;
        if (c->pwm_duty_pct > 100) return false;
        if ((i == OC_OUT_M1 || i == OC_OUT_M2) && (c->pwm_frequency_hz < 1000 || c->pwm_frequency_hz > 40000)) return false;
        if (!(i == OC_OUT_M1 || i == OC_OUT_M2) && c->pwm_frequency_hz > 40000) return false;
        if (c->esc_arm_hold_ms > 10000 || c->esc_arm_low_ms > 10000 || c->esc_arm_high_ms > 10000 || c->esc_arm_final_low_ms > 10000) return false;
        if (c->esc_arm_low_us > 3000 || c->esc_arm_high_us > 3000 || c->esc_arm_low_us >= c->esc_arm_high_us) return false;
        if (c->weapon_safety && c->failsafe == OC_FAILSAFE_HOLD_LAST) return false;
        if (c->min_pulse_us || c->center_pulse_us || c->max_pulse_us) {
            if (!(c->min_pulse_us < c->center_pulse_us && c->center_pulse_us < c->max_pulse_us)) return false;
        }
    }
    return true;
}

// ---- Lifecycle -----------------------------------------------------------

void output_config_reset_defaults(void) {
    memcpy(s_cfg, kDefaults, sizeof(s_cfg));
    s_drive_mode = OC_DRIVE_TANK_SPLIT;
    s_drive_setup = drive_setup_for_legacy_mode(OC_DRIVE_TANK_SPLIT);
    s_max_paired = OC_MAX_PAIRED_DEFAULT;
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
    s_drive_setup = drive_setup_for_legacy_mode(s_drive_mode);
    if (nvs_open(OC_NVS_NAMESPACE, NVS_READONLY, &h) == ESP_OK) {
        oc_drive_setup_t setup;
        size_t setup_len = sizeof(setup);
        esp_err_t setup_err = nvs_get_blob(h, OC_NVS_KEY_DRIVE_SETUP, &setup, &setup_len);
        nvs_close(h);
        if (setup_err == ESP_OK && setup_len == sizeof(setup) && drive_setup_is_sane(&setup)) {
            s_drive_setup = setup;
        }
    }

    // Max paired is its own small key. Missing/out-of-range falls back
    // to OC_MAX_PAIRED_DEFAULT.
    s_max_paired = OC_MAX_PAIRED_DEFAULT;
    if (nvs_open(OC_NVS_NAMESPACE, NVS_READONLY, &h) == ESP_OK) {
        uint8_t mp = 0;
        esp_err_t mp_err = nvs_get_u8(h, OC_NVS_KEY_MAX_PAIRED, &mp);
        nvs_close(h);
        if (mp_err == ESP_OK && mp >= 1 && mp <= OC_MAX_PAIRED_CAP) {
            s_max_paired = mp;
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

const oc_drive_setup_t *output_config_get_drive_setup(void) {
    return &s_drive_setup;
}

esp_err_t output_config_set_drive_setup(const oc_drive_setup_t *setup) {
    if (!drive_setup_is_sane(setup)) return ESP_ERR_INVALID_ARG;
    s_drive_setup = *setup;
    return save_all();
}

const char *output_config_drive_layout_name(oc_drive_layout_t layout) {
    if ((unsigned)layout >= OC_DRIVE_LAYOUT__COUNT) return "differential";
    return kDriveLayoutNames[layout];
}

const char *output_config_drive_method_name(oc_drive_method_t method) {
    if ((unsigned)method >= OC_DRIVE_METHOD__COUNT) return "tank";
    return kDriveMethodNames[method];
}

const char *output_config_drive_axis_name(oc_drive_axis_t axis) {
    if ((unsigned)axis >= OC_DRIVE_AXIS__COUNT) return "NONE";
    return kDriveAxisNames[axis];
}

bool output_config_drive_layout_from_str(const char *s, oc_drive_layout_t *out) {
    int v;
    if (!table_lookup(s, kDriveLayoutNames, OC_DRIVE_LAYOUT__COUNT, &v)) return false;
    *out = (oc_drive_layout_t)v;
    return true;
}

bool output_config_drive_method_from_str(const char *s, oc_drive_method_t *out) {
    int v;
    if (!table_lookup(s, kDriveMethodNames, OC_DRIVE_METHOD__COUNT, &v)) return false;
    *out = (oc_drive_method_t)v;
    return true;
}

bool output_config_drive_axis_from_str(const char *s, oc_drive_axis_t *out) {
    int v;
    if (!table_lookup(s, kDriveAxisNames, OC_DRIVE_AXIS__COUNT, &v)) return false;
    *out = (oc_drive_axis_t)v;
    return true;
}

uint8_t output_config_get_max_paired(void) {
    return s_max_paired;
}

esp_err_t output_config_set_max_paired(uint8_t n) {
    if (n < 1 || n > OC_MAX_PAIRED_CAP) return ESP_ERR_INVALID_ARG;
    s_max_paired = n;
    return save_all();
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
// Hand-rolled because adding ArduinoJson for a 4-element config is
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
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"drive\":{");
    ok &= json_append_raw(out_buf, out_buf_len, &used, "\"layout\":");
    ok &= json_append_quoted_token(out_buf, out_buf_len, &used, output_config_drive_layout_name(s_drive_setup.layout));
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"method\":");
    ok &= json_append_quoted_token(out_buf, out_buf_len, &used, output_config_drive_method_name(s_drive_setup.method));
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"left_axis\":");
    ok &= json_append_quoted_token(out_buf, out_buf_len, &used, output_config_drive_axis_name(s_drive_setup.left_axis));
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"right_axis\":");
    ok &= json_append_quoted_token(out_buf, out_buf_len, &used, output_config_drive_axis_name(s_drive_setup.right_axis));
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"throttle_axis\":");
    ok &= json_append_quoted_token(out_buf, out_buf_len, &used, output_config_drive_axis_name(s_drive_setup.throttle_axis));
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"steering_axis\":");
    ok &= json_append_quoted_token(out_buf, out_buf_len, &used, output_config_drive_axis_name(s_drive_setup.steering_axis));
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"drive_motor_output\":");
    ok &= json_append_quoted_token(out_buf, out_buf_len, &used, output_config_output_id_str(s_drive_setup.drive_motor_output));
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"steering_output\":");
    ok &= json_append_quoted_token(out_buf, out_buf_len, &used, output_config_output_id_str(s_drive_setup.steering_output));
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"precision_source\":");
    ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kSourceNames[s_drive_setup.precision_source]);
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"precision_scale_pct\":");
    ok &= json_append_int(out_buf, out_buf_len, &used, s_drive_setup.precision_scale_pct);
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"brake_source\":");
    ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kSourceNames[s_drive_setup.brake_source]);
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"invert_steering_source\":");
    ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kSourceNames[s_drive_setup.invert_steering_source]);
    ok &= json_append_raw(out_buf, out_buf_len, &used, "}");
    ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"max_paired\":");
    ok &= json_append_int(out_buf, out_buf_len, &used, s_max_paired);
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
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"motor_mode\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kMotorModeNames[c->motor_mode]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"purpose\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kPurposeNames[c->purpose]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"protocol\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kProtocolNames[c->protocol]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"semantics\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kSemanticsNames[c->semantics]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"pulse\":{");
        ok &= json_append_raw(out_buf, out_buf_len, &used, "\"min_us\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->min_pulse_us);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"center_us\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->center_pulse_us);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"max_us\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->max_pulse_us);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"frame_hz\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->frame_hz);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"neutral_deadzone\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->neutral_deadzone_pct);
        ok &= json_append_raw(out_buf, out_buf_len, &used, "}");
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"safety\":{");
        ok &= json_append_raw(out_buf, out_buf_len, &used, "\"weapon\":");
        ok &= json_append_raw(out_buf, out_buf_len, &used, c->weapon_safety ? "true" : "false");
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"failsafe\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kFailsafeNames[c->failsafe]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"weapon_mode\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kWeaponModeNames[c->weapon_mode]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"arming_source\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kSourceNames[c->arming_source]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"deadman_source\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kSourceNames[c->deadman_source]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, "}");
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"esc_arm\":{");
        ok &= json_append_raw(out_buf, out_buf_len, &used, "\"mode\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kEscArmModeNames[c->esc_arm_mode]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"source\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kSourceNames[c->esc_arm_source]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"hold_ms\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->esc_arm_hold_ms);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"low_us\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->esc_arm_low_us);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"high_us\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->esc_arm_high_us);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"low_ms\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->esc_arm_low_ms);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"high_ms\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->esc_arm_high_ms);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"final_low_ms\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->esc_arm_final_low_ms);
        ok &= json_append_raw(out_buf, out_buf_len, &used, "}");
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"power\":{");
        ok &= json_append_raw(out_buf, out_buf_len, &used, "\"GOOD\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kPowerNames[c->power_good]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"WARN\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kPowerNames[c->power_warn]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"LOW\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kPowerNames[c->power_low]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, "}");
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"gpio\":{");
        ok &= json_append_raw(out_buf, out_buf_len, &used, "\"active_high\":");
        ok &= json_append_raw(out_buf, out_buf_len, &used, c->active_high ? "true" : "false");
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"default_state\":");
        ok &= json_append_raw(out_buf, out_buf_len, &used, c->default_state ? "true" : "false");
        ok &= json_append_raw(out_buf, out_buf_len, &used, "}");
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"digital_mode\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kDigitalModeNames[c->digital_mode]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"digital_preset\":");
        ok &= json_append_quoted_token(out_buf, out_buf_len, &used, kDigitalPresetNames[c->digital_preset]);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"digital_on_threshold\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->digital_on_threshold);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"digital_off_threshold\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->digital_off_threshold);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"digital_custom_pct\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->digital_custom_pct);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"pwm\":{");
        ok &= json_append_raw(out_buf, out_buf_len, &used, "\"frequency_hz\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->pwm_frequency_hz);
        ok &= json_append_raw(out_buf, out_buf_len, &used, ",\"duty_pct\":");
        ok &= json_append_int(out_buf, out_buf_len, &used, c->pwm_duty_pct);
        ok &= json_append_raw(out_buf, out_buf_len, &used, "}");
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

// Parse a non-negative integer at `cursor` and advance past it.
// On success returns true and writes the value to *out. Rejects
// negative numbers, scientific notation, leading whitespace ints
// (callers strip whitespace before invoking), and overflow.
static bool parse_bare_int_value(const char **cursor, int *out) {
    const char *p = *cursor;
    char *end = NULL;
    errno = 0;
    long v = strtol(p, &end, 10);
    if (end == p) return false;       // no digits
    if (errno == ERANGE) return false; // overflow
    if (v < 0 || v > INT_MAX) return false;
    *out = (int)v;
    *cursor = end;
    return true;
}

static bool parse_bare_bool_value(const char **cursor, bool *out) {
    const char *p = *cursor;
    while (*p && isspace((unsigned char)*p)) p++;
    if (strncmp(p, "true", 4) == 0) {
        *out = true;
        *cursor = p + 4;
        return true;
    }
    if (strncmp(p, "false", 5) == 0) {
        *out = false;
        *cursor = p + 5;
        return true;
    }
    return false;
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

static bool table_lookup(const char *s, const char *const *names, int count, int *out) {
    if (!s || !out) return false;
    for (int i = 0; i < count; i++) {
        if (strcasecmp(s, names[i]) == 0) {
            *out = i;
            return true;
        }
    }
    return false;
}

static bool purpose_from_str(const char *s, oc_purpose_t *out) {
    int v;
    if (!table_lookup(s, kPurposeNames, OC_PURPOSE__COUNT, &v)) return false;
    *out = (oc_purpose_t)v;
    return true;
}

static bool protocol_from_str(const char *s, oc_protocol_t *out) {
    int v;
    if (!table_lookup(s, kProtocolNames, OC_PROTO__COUNT, &v)) return false;
    *out = (oc_protocol_t)v;
    return true;
}

static bool semantics_from_str(const char *s, oc_semantics_t *out) {
    int v;
    if (!table_lookup(s, kSemanticsNames, OC_SEM__COUNT, &v)) return false;
    *out = (oc_semantics_t)v;
    return true;
}

static bool failsafe_from_str(const char *s, oc_failsafe_t *out) {
    int v;
    if (!table_lookup(s, kFailsafeNames, 2, &v)) return false;
    *out = (oc_failsafe_t)v;
    return true;
}

static bool weapon_mode_from_str(const char *s, oc_weapon_safety_mode_t *out) {
    int v;
    if (!table_lookup(s, kWeaponModeNames, 3, &v)) return false;
    *out = (oc_weapon_safety_mode_t)v;
    return true;
}

static bool esc_arm_mode_from_str(const char *s, oc_esc_arm_mode_t *out) {
    int v;
    if (!table_lookup(s, kEscArmModeNames, OC_ESC_ARM__COUNT, &v)) return false;
    *out = (oc_esc_arm_mode_t)v;
    return true;
}

static bool power_from_str(const char *s, oc_power_override_t *out) {
    int v;
    if (!table_lookup(s, kPowerNames, 4, &v)) return false;
    *out = (oc_power_override_t)v;
    return true;
}

static bool digital_mode_from_str(const char *s, oc_digital_mode_t *out) {
    int v;
    if (!table_lookup(s, kDigitalModeNames, OC_DIGITAL_MODE__COUNT, &v)) return false;
    *out = (oc_digital_mode_t)v;
    return true;
}

static bool digital_preset_from_str(const char *s, oc_digital_preset_t *out) {
    int v;
    if (!table_lookup(s, kDigitalPresetNames, OC_DIGITAL_PRESET__COUNT, &v)) return false;
    *out = (oc_digital_preset_t)v;
    return true;
}

static bool motor_mode_from_str(const char *s, oc_motor_mode_t *out) {
    int v;
    if (!table_lookup(s, kMotorModeNames, OC_MOTOR_MODE__COUNT, &v)) return false;
    *out = (oc_motor_mode_t)v;
    return true;
}

static bool purpose_protocol_is_valid(oc_purpose_t purpose, oc_protocol_t protocol) {
    switch (purpose) {
        case OC_PURPOSE_DISABLED: return protocol == OC_PROTO_NONE;
        case OC_PURPOSE_DRIVE: return protocol == OC_PROTO_NONE;
        case OC_PURPOSE_SERVO:
            return protocol == OC_PROTO_RC_SERVO_PWM || protocol == OC_PROTO_RC_SERVO_PPM ||
                   protocol == OC_PROTO_RC_SERVO_PWM_100 || protocol == OC_PROTO_RC_SERVO_PWM_200 ||
                   protocol == OC_PROTO_RC_SERVO_PWM_333;
        case OC_PURPOSE_ESC:
            return protocol == OC_PROTO_RC_ESC_PWM || protocol == OC_PROTO_RC_ESC_PWM_100 ||
                   protocol == OC_PROTO_RC_ESC_PWM_250 || protocol == OC_PROTO_RC_ESC_PWM_333 ||
                   protocol == OC_PROTO_RC_ESC_PWM_490 || protocol == OC_PROTO_ONESHOT ||
                   protocol == OC_PROTO_ONESHOT125 || protocol == OC_PROTO_ONESHOT42 ||
                   protocol == OC_PROTO_MULTISHOT;
        case OC_PURPOSE_DIGITAL_OUTPUT:
        case OC_PURPOSE_DIGITAL_INPUT: return protocol == OC_PROTO_GPIO;
        case OC_PURPOSE_PWM_ACCESSORY: return protocol == OC_PROTO_PWM_DUTY;
        default: return false;
    }
}

static oc_power_override_t output_config_effective_power(const oc_output_cfg_t *cfg, uint8_t battery_state) {
    // Constants.h defines BATTERY_GOOD=1, BATTERY_WARN=2, BATTERY_LOW=3.
    // Keep this C component independent of Arduino/C++ headers by matching
    // those stable numeric states at the interface boundary.
    switch (battery_state) {
        case 1: return cfg->power_good;
        case 2: return cfg->power_warn;
        case 3: return cfg->power_low;
        default: return OC_POWER_DEFAULT;
    }
}

static bool output_config_default_allowed_for_state(const oc_output_cfg_t *cfg, uint8_t battery_state) {
    if (cfg->weapon_safety && battery_state == 3) {
        return false;
    }
    return true;
}

bool output_config_channel_allowed(oc_output_id_t id, uint8_t battery_state) {
    const oc_output_cfg_t *cfg = output_config_get(id);
    switch (output_config_effective_power(cfg, battery_state)) {
        case OC_POWER_ALLOW:
        case OC_POWER_REDUCE:
            return true;
        case OC_POWER_DISABLE:
            return false;
        case OC_POWER_DEFAULT:
        default:
            return output_config_default_allowed_for_state(cfg, battery_state);
    }
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

        if (strcmp(key, "deadzone") == 0 || strcmp(key, "min_pulse_us") == 0 ||
            strcmp(key, "center_pulse_us") == 0 || strcmp(key, "max_pulse_us") == 0 ||
            strcmp(key, "frame_hz") == 0 || strcmp(key, "neutral_deadzone") == 0 ||
            strcmp(key, "ramp_ms") == 0 || strcmp(key, "pwm_frequency_hz") == 0 ||
            strcmp(key, "pwm_duty_pct") == 0 || strcmp(key, "digital_on_threshold") == 0 ||
            strcmp(key, "digital_off_threshold") == 0 || strcmp(key, "digital_custom_pct") == 0 ||
            strcmp(key, "esc_arm_hold_ms") == 0 || strcmp(key, "esc_arm_low_us") == 0 ||
            strcmp(key, "esc_arm_high_us") == 0 || strcmp(key, "esc_arm_low_ms") == 0 ||
            strcmp(key, "esc_arm_high_ms") == 0 || strcmp(key, "esc_arm_final_low_ms") == 0) {
            while (*p && isspace((unsigned char)*p)) p++;
            if (*p != ':') return false;
            p++;
            while (*p && isspace((unsigned char)*p)) p++;
            char *end = NULL;
            long d = strtol(p, &end, 10);
            bool is_digital_threshold = strcmp(key, "digital_on_threshold") == 0 ||
                                        strcmp(key, "digital_off_threshold") == 0;
            if (end == p || d < (is_digital_threshold ? -1024 : 0) || d > 65535) return false;
            p = end;
            if (strcmp(key, "deadzone") == 0) {
                if (d < 0 || d > 50) return false;
                if (s_cfg[id].deadzone_pct != (uint8_t)d) { s_cfg[id].deadzone_pct = (uint8_t)d; dirty = true; }
            } else if (strcmp(key, "min_pulse_us") == 0) {
                if (s_cfg[id].min_pulse_us != (uint16_t)d) { s_cfg[id].min_pulse_us = (uint16_t)d; dirty = true; }
            } else if (strcmp(key, "center_pulse_us") == 0) {
                if (s_cfg[id].center_pulse_us != (uint16_t)d) { s_cfg[id].center_pulse_us = (uint16_t)d; dirty = true; }
            } else if (strcmp(key, "max_pulse_us") == 0) {
                if (s_cfg[id].max_pulse_us != (uint16_t)d) { s_cfg[id].max_pulse_us = (uint16_t)d; dirty = true; }
            } else if (strcmp(key, "frame_hz") == 0) {
                if (s_cfg[id].frame_hz != (uint16_t)d) { s_cfg[id].frame_hz = (uint16_t)d; dirty = true; }
            } else if (strcmp(key, "neutral_deadzone") == 0) {
                if (d > 50) return false;
                if (s_cfg[id].neutral_deadzone_pct != (uint8_t)d) { s_cfg[id].neutral_deadzone_pct = (uint8_t)d; dirty = true; }
            } else if (strcmp(key, "ramp_ms") == 0) {
                if (s_cfg[id].ramp_ms != (uint16_t)d) { s_cfg[id].ramp_ms = (uint16_t)d; dirty = true; }
            } else if (strcmp(key, "pwm_frequency_hz") == 0) {
                if ((id == OC_OUT_M1 || id == OC_OUT_M2) && (d < 1000 || d > 40000)) return false;
                if (s_cfg[id].pwm_frequency_hz != (uint16_t)d) { s_cfg[id].pwm_frequency_hz = (uint16_t)d; dirty = true; }
            } else if (strcmp(key, "pwm_duty_pct") == 0) {
                if (d > 100) return false;
                if (s_cfg[id].pwm_duty_pct != (uint8_t)d) { s_cfg[id].pwm_duty_pct = (uint8_t)d; dirty = true; }
            } else if (strcmp(key, "esc_arm_hold_ms") == 0) {
                if (d > 10000) return false;
                if (s_cfg[id].esc_arm_hold_ms != (uint16_t)d) { s_cfg[id].esc_arm_hold_ms = (uint16_t)d; dirty = true; }
            } else if (strcmp(key, "esc_arm_low_us") == 0) {
                if (d > 3000) return false;
                if (s_cfg[id].esc_arm_low_us != (uint16_t)d) { s_cfg[id].esc_arm_low_us = (uint16_t)d; dirty = true; }
            } else if (strcmp(key, "esc_arm_high_us") == 0) {
                if (d > 3000) return false;
                if (s_cfg[id].esc_arm_high_us != (uint16_t)d) { s_cfg[id].esc_arm_high_us = (uint16_t)d; dirty = true; }
            } else if (strcmp(key, "esc_arm_low_ms") == 0) {
                if (d > 10000) return false;
                if (s_cfg[id].esc_arm_low_ms != (uint16_t)d) { s_cfg[id].esc_arm_low_ms = (uint16_t)d; dirty = true; }
            } else if (strcmp(key, "esc_arm_high_ms") == 0) {
                if (d > 10000) return false;
                if (s_cfg[id].esc_arm_high_ms != (uint16_t)d) { s_cfg[id].esc_arm_high_ms = (uint16_t)d; dirty = true; }
            } else if (strcmp(key, "esc_arm_final_low_ms") == 0) {
                if (d > 10000) return false;
                if (s_cfg[id].esc_arm_final_low_ms != (uint16_t)d) { s_cfg[id].esc_arm_final_low_ms = (uint16_t)d; dirty = true; }
            } else if (strcmp(key, "digital_on_threshold") == 0) {
                if (d < -1024 || d > 1024) return false;
                if (s_cfg[id].digital_on_threshold != (int16_t)d) { s_cfg[id].digital_on_threshold = (int16_t)d; dirty = true; }
            } else if (strcmp(key, "digital_off_threshold") == 0) {
                if (d < -1024 || d > 1024) return false;
                if (s_cfg[id].digital_off_threshold != (int16_t)d) { s_cfg[id].digital_off_threshold = (int16_t)d; dirty = true; }
            } else if (strcmp(key, "digital_custom_pct") == 0) {
                if (d > 100) return false;
                if (s_cfg[id].digital_custom_pct != (uint8_t)d) { s_cfg[id].digital_custom_pct = (uint8_t)d; dirty = true; }
            }
        } else if (strcmp(key, "weapon_safety") == 0 || strcmp(key, "active_high") == 0 ||
                   strcmp(key, "default_state") == 0) {
            while (*p && isspace((unsigned char)*p)) p++;
            if (*p != ':') return false;
            p++;
            bool b;
            if (!parse_bare_bool_value(&p, &b)) return false;
            if (strcmp(key, "weapon_safety") == 0) {
                if (s_cfg[id].weapon_safety != b) { s_cfg[id].weapon_safety = b; dirty = true; }
            } else if (strcmp(key, "active_high") == 0) {
                if (s_cfg[id].active_high != b) { s_cfg[id].active_high = b; dirty = true; }
            } else {
                if (s_cfg[id].default_state != b) { s_cfg[id].default_state = b; dirty = true; }
            }
        } else {
            char value[24] = {0};
            if (!parse_string_value(&p, value, sizeof(value))) return false;

            if (strcmp(key, "direction") == 0) {
                if (strcmp(value, "normal") == 0) {
                    if (s_cfg[id].direction != OC_DIR_NORMAL) { s_cfg[id].direction = OC_DIR_NORMAL; dirty = true; }
                } else if (strcmp(value, "reversed") == 0) {
                    if (s_cfg[id].direction != OC_DIR_REVERSED) { s_cfg[id].direction = OC_DIR_REVERSED; dirty = true; }
                } else return false;
            } else if (strcmp(key, "display_name") == 0) {
                if (strlen(value) > OC_DISPLAY_NAME_MAX_LEN) return false;
                if (strcmp(s_cfg[id].display_name, value) != 0) {
                    memset(s_cfg[id].display_name, 0, sizeof(s_cfg[id].display_name));
                    strncpy(s_cfg[id].display_name, value, OC_DISPLAY_NAME_MAX_LEN);
                    dirty = true;
                }
            } else if (strcmp(key, "purpose") == 0) {
                oc_purpose_t purpose;
                if (!purpose_from_str(value, &purpose)) return false;
                if (s_cfg[id].purpose != purpose) { s_cfg[id].purpose = purpose; dirty = true; }
            } else if (strcmp(key, "protocol") == 0) {
                oc_protocol_t protocol;
                if (!protocol_from_str(value, &protocol)) return false;
                if (s_cfg[id].protocol != protocol) { s_cfg[id].protocol = protocol; dirty = true; }
            } else if (strcmp(key, "semantics") == 0) {
                oc_semantics_t semantics;
                if (!semantics_from_str(value, &semantics)) return false;
                if (s_cfg[id].semantics != semantics) { s_cfg[id].semantics = semantics; dirty = true; }
            } else if (strcmp(key, "failsafe") == 0) {
                oc_failsafe_t failsafe;
                if (!failsafe_from_str(value, &failsafe)) return false;
                if (s_cfg[id].weapon_safety && failsafe == OC_FAILSAFE_HOLD_LAST) return false;
                if (s_cfg[id].failsafe != failsafe) { s_cfg[id].failsafe = failsafe; dirty = true; }
            } else if (strcmp(key, "weapon_mode") == 0) {
                oc_weapon_safety_mode_t mode;
                if (!weapon_mode_from_str(value, &mode)) return false;
                if (s_cfg[id].weapon_mode != mode) { s_cfg[id].weapon_mode = mode; dirty = true; }
            } else if (strcmp(key, "esc_arm_mode") == 0) {
                oc_esc_arm_mode_t mode;
                if (!esc_arm_mode_from_str(value, &mode)) return false;
                if (s_cfg[id].esc_arm_mode != mode) { s_cfg[id].esc_arm_mode = mode; dirty = true; }
            } else if (strcmp(key, "esc_arm_source") == 0) {
                oc_source_id_t s;
                if (!output_config_source_from_str(value, &s)) return false;
                if (s_cfg[id].esc_arm_source != s) { s_cfg[id].esc_arm_source = s; dirty = true; }
            } else if (strcmp(key, "arming_source") == 0) {
                oc_source_id_t s;
                if (!output_config_source_from_str(value, &s)) return false;
                if (s_cfg[id].arming_source != s) { s_cfg[id].arming_source = s; dirty = true; }
            } else if (strcmp(key, "deadman_source") == 0) {
                oc_source_id_t s;
                if (!output_config_source_from_str(value, &s)) return false;
                if (s_cfg[id].deadman_source != s) { s_cfg[id].deadman_source = s; dirty = true; }
            } else if (strcmp(key, "power_good") == 0) {
                oc_power_override_t pow;
                if (!power_from_str(value, &pow)) return false;
                if (s_cfg[id].power_good != pow) { s_cfg[id].power_good = pow; dirty = true; }
            } else if (strcmp(key, "power_warn") == 0) {
                oc_power_override_t pow;
                if (!power_from_str(value, &pow)) return false;
                if (s_cfg[id].power_warn != pow) { s_cfg[id].power_warn = pow; dirty = true; }
            } else if (strcmp(key, "power_low") == 0) {
                oc_power_override_t pow;
                if (!power_from_str(value, &pow)) return false;
                if (s_cfg[id].power_low != pow) { s_cfg[id].power_low = pow; dirty = true; }
            } else if (strcmp(key, "digital_mode") == 0) {
                oc_digital_mode_t mode;
                if (!digital_mode_from_str(value, &mode)) return false;
                if (s_cfg[id].digital_mode != mode) { s_cfg[id].digital_mode = mode; dirty = true; }
            } else if (strcmp(key, "digital_preset") == 0) {
                oc_digital_preset_t preset;
                if (!digital_preset_from_str(value, &preset)) return false;
                if (s_cfg[id].digital_preset != preset) { s_cfg[id].digital_preset = preset; dirty = true; }
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
            } else if (strcmp(key, "motor_mode") == 0) {
                oc_motor_mode_t mode;
                if (!motor_mode_from_str(value, &mode)) return false;
                if (s_cfg[id].motor_mode != mode) { s_cfg[id].motor_mode = mode; dirty = true; }
            } else {
                // Unknown string key: accept silently for forward-compat.
            }
        }

        while (*p && isspace((unsigned char)*p)) p++;
        if (*p == ',') p++;
    }
    if (!purpose_protocol_is_valid(s_cfg[id].purpose, s_cfg[id].protocol)) return false;
    if (!cfg_blob_is_sane(s_cfg)) return false;
    return !dirty ? true : true; // dirty is informational; we always report apply ok
}


static bool apply_drive_patch(const char *body) {
    oc_drive_setup_t next = s_drive_setup;
    const char *p = body;
    if (*p != '{') return false;
    p++;
    while (*p && *p != '}') {
        while (*p && isspace((unsigned char)*p)) p++;
        if (*p == '}') break;
        if (*p != '"') return false;
        const char *key_start = ++p;
        while (*p && *p != '"') {
            if (*p == '\\' && p[1]) p++;
            p++;
        }
        if (*p != '"') return false;
        size_t klen = (size_t)(p - key_start);
        char key[32] = {0};
        if (klen >= sizeof(key)) return false;
        memcpy(key, key_start, klen);
        p++;
        while (*p && isspace((unsigned char)*p)) p++;
        if (*p != ':') return false;
        p++;
        while (*p && isspace((unsigned char)*p)) p++;
        if (strcmp(key, "precision_scale_pct") == 0) {
            int v;
            if (!parse_bare_int_value(&p, &v)) return false;
            if (v < 0 || v > 100) return false;
            next.precision_scale_pct = (uint8_t)v;
        } else {
            char value[24] = {0};
            if (!parse_bare_string_value(&p, value, sizeof(value))) return false;
            if (strcmp(key, "layout") == 0) {
                if (!output_config_drive_layout_from_str(value, &next.layout)) return false;
                if (next.layout == OC_DRIVE_LAYOUT_DIFFERENTIAL && next.method == OC_DRIVE_METHOD_SERVO_STEERING) next.method = OC_DRIVE_METHOD_ARCADE;
                if (next.layout == OC_DRIVE_LAYOUT_SERVO_STEERING) next.method = OC_DRIVE_METHOD_SERVO_STEERING;
            } else if (strcmp(key, "method") == 0) {
                if (!output_config_drive_method_from_str(value, &next.method)) return false;
            } else if (strcmp(key, "left_axis") == 0) {
                if (!output_config_drive_axis_from_str(value, &next.left_axis)) return false;
            } else if (strcmp(key, "right_axis") == 0) {
                if (!output_config_drive_axis_from_str(value, &next.right_axis)) return false;
            } else if (strcmp(key, "throttle_axis") == 0) {
                if (!output_config_drive_axis_from_str(value, &next.throttle_axis)) return false;
            } else if (strcmp(key, "steering_axis") == 0) {
                if (!output_config_drive_axis_from_str(value, &next.steering_axis)) return false;
            } else if (strcmp(key, "drive_motor_output") == 0) {
                if (!output_config_id_from_str(value, &next.drive_motor_output)) return false;
            } else if (strcmp(key, "steering_output") == 0) {
                if (!output_config_id_from_str(value, &next.steering_output)) return false;
            } else if (strcmp(key, "precision_source") == 0) {
                if (!output_config_source_from_str(value, &next.precision_source)) return false;
            } else if (strcmp(key, "brake_source") == 0) {
                if (!output_config_source_from_str(value, &next.brake_source)) return false;
            } else if (strcmp(key, "invert_steering_source") == 0) {
                if (!output_config_source_from_str(value, &next.invert_steering_source)) return false;
            }
        }
        while (*p && isspace((unsigned char)*p)) p++;
        if (*p == ',') p++;
    }
    if (!drive_setup_is_sane(&next)) return false;
    s_drive_setup = next;
    return true;
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
            s_drive_setup = drive_setup_for_legacy_mode(mode);
            while (*p && isspace((unsigned char)*p)) p++;
            if (*p == ',') p++;
            continue;
        }

        if (strcmp(key, "max_paired") == 0) {
            int n;
            if (!parse_bare_int_value(&p, &n)) return ESP_ERR_INVALID_ARG;
            if (n < 1 || n > OC_MAX_PAIRED_CAP) return ESP_ERR_INVALID_ARG;
            s_max_paired = (uint8_t)n;
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

        if (strcmp(key, "Weapon") == 0) {
            return ESP_ERR_INVALID_ARG;
        }
        if (strcmp(key, "drive") == 0) {
            if (!apply_drive_patch(body)) return ESP_ERR_INVALID_ARG;
        } else {
            oc_output_id_t id;
            if (output_config_id_from_str(key, &id)) {
                if (!apply_patch_one(id, body)) return ESP_ERR_INVALID_ARG;
            }
        }
        // unknown output key: ignored (forward-compat)
        while (*p && isspace((unsigned char)*p)) p++;
        if (*p == ',') p++;
    }

    return save_all();
}
