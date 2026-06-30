// board_config.h — Board revision abstraction layer
//
// Purpose: One source code that runs on multiple hardware revisions.
// Select at compile time with -DBOARD_REV=N (see platformio.ini).
//
// Revisions supported:
//   BOARD_REV=2  — Generic Robot Controller v2 (current production, has v1.3 firmware)
//   BOARD_REV=3  — Generic Robot Controller v3 (designed, not yet fabricated)
//
// See docs/BOARD_HARDWARE.md for the full board reference.
//
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <stdint.h>

// ---- Board revision selection ----

#ifndef BOARD_REV
#  define BOARD_REV 2   // Default to current production
#endif

// ---- Common constants (same on both boards) ----

// Standard Bluetooth HID gamepad report ranges.
// The HID parser rescales these to the BP32-style range the rest of the
// firmware expects (-512..511 axes, 0..1023 triggers).
#define HID_AXIS_MIN_RAW    0
#define HID_AXIS_MAX_RAW    255
#define HID_AXIS_CENTER     127
#define HID_AXIS_SCALE      4     // (v - 127) * 4 ≈ -508..508
#define HID_TRIGGER_SCALE   4     // raw 0..255 -> 0..1020

// Battery monitor
#define NUM_OF_CELLS            3
#define MIN_MVOLT_PER_CELL      3600
#define WARN_MVOLT_PER_CELL     3750
#define BATTERY_MULTIPLIER      8.95f
#define EMA_ALPHA               0.1f
#define BATT_HYSTERESIS_MV      100
#define BATTERY_DEBOUNCE_MS     3000

// Motor control
#define DRIVE_MOTOR_PWM_FREQ        20000
#define DRIVE_MOTOR_PWM_RESOLUTION  8
#define DRIVE_MOTOR_PWM_MAX         255
#define ESC_PWM_FREQ                2000
#define ESC_PWM_RESOLUTION          8
#define ESC_MIN_PULSEWIDTH_US       125
#define ESC_MID_PULSEWIDTH_US       188
#define ESC_MAX_PULSEWIDTH_US       250

// Controller timeouts / button handling
#define CONTROLLER_TIMEOUT_MS   1000
#define DEBOUNCE_MS             10
#define LONG_PRESS_MS           1000
#define BUTTON_POLL_MS          50

// ---- Per-board pin assignments ----

#if BOARD_REV == 2

    // v2 board (Generic Robot Controller v2)
    // .epro: ProPrj_Generic_Robot_Controller_ver2_temp_2026-06-30.epro
    //
    // NOTE: v2 pinout INFERRED from v3 schematic (same chip, same designators
    // for adjacent components, same U2/U3 = motor drivers). See
    // docs/BOARD_HARDWARE.md Section 7 for open questions.

    #define BOARD_NAME                "Generic Robot Controller v2"
    #define BOARD_REVISION_STRING     "v2 (current production)"

    // ESP32-C3-MINI-1 GPIO assignments
    #define PIN_MOTOR1_IN1            0    // GPIO0  -> DRV8871 IN1 (M1)
    #define PIN_MOTOR1_IN2            1    // GPIO1  -> DRV8871 IN2 (M1)
    #define PIN_MOTOR2_IN1            21   // TXD0   -> DRV8871 IN1 (M2)
    #define PIN_MOTOR2_IN2            10   // GPIO10 -> DRV8871 IN2 (M2)
    #define PIN_SERVO1                4    // GPIO4  -> CN? SERVO1
    #define PIN_SERVO2                5    // GPIO5  -> CN? SERVO2

    // Drum: NOT on v2 schematic. v1.3 firmware's `Drum` class may be
    // driving a non-existent pin. Set to HAS_DRUM=0 until verified.
    #define PIN_DRUM_PWM              255  // Invalid - drum not on v2
    #define HAS_DRUM                  0

    // Sensors / UI
    #define PIN_BATT_MEAS             3    // GPIO3  -> ADC battery divider
    #define PIN_MODE_BUTTON           6    // GPIO6  -> MODE_BUTTON
    #define PIN_DEBUG_LED             7    // GPIO7  -> LED1 (debug)
    #define PIN_NEOPIXEL              8    // GPIO8  -> WS2812 LED (also I2C SCL!)

    // I2C bus (shared: IMU on SDA/SCL, but also NEOPIXEL on same pins?)
    // NOTE: v2 schematic likely has a pin conflict here - verify
    #define PIN_SDA                   2    // GPIO2  -> I2C SDA
    #define PIN_SCL                   8    // GPIO8  -> I2C SCL  *** SHARED WITH NEOPIXEL ***

    // Power gating
    #define PIN_5V_EXT_EN             20   // RXD0  -> TPS259241 eFuse EN
    #define PIN_BOOT_BUTTON           9    // GPIO9  -> BOOT (ESP32 strapping pin)

    // Number of drive motors
    #define NUM_DRIVE_MOTORS          2

    // Has IMU (LSM6DS3)
    #define HAS_IMU                   1

    // Has NeoPixel LED strip
    #define HAS_NEOPIXEL              1

#elif BOARD_REV == 3

    // v3 board (next revision, not yet fabricated)
    // .epro: ProPrj_Generic_Robot_Controller_ver2_2025-08-17.epro
    //
    // Pinout extracted from rendered schematic. Confirmed via vision model
    // reading the page-by-page schematic images. See docs/BOARD_HARDWARE.md.

    #define BOARD_NAME                "Generic Robot Controller v3"
    #define BOARD_REVISION_STRING     "v3 (designed, not fabricated)"

    // ESP32-C3-MINI-1 GPIO assignments (matches v3 schematic)
    #define PIN_MOTOR1_IN1            0    // GPIO0  -> MOTOR1_IN1 (R3 220Ω)
    #define PIN_MOTOR1_IN2            1    // GPIO1  -> MOTOR1_IN2 (R4 220Ω)
    #define PIN_MOTOR2_IN1            21   // TXD0   -> MOTOR2_IN1 (R8 220Ω)
    #define PIN_MOTOR2_IN2            10   // GPIO10 -> MOTOR2_IN2 (R5 220Ω)
    #define PIN_SERVO1                4    // GPIO4  -> SERVO1
    #define PIN_SERVO2                5    // GPIO5  -> SERVO2

    // Drum: TBD on v3. The v3 schematic doesn't have a clear drum signal,
    // so we set HAS_DRUM=0 by default. Override if v3 design adds it.
    #define PIN_DRUM_PWM              255  // Invalid - drum not yet on v3
    #define HAS_DRUM                  0

    // Sensors / UI
    #define PIN_BATT_MEAS             3    // GPIO3  -> BATT_MEAS (ADC)
    #define PIN_MODE_BUTTON           6    // GPIO6  -> MODE_BUTTON
    #define PIN_DEBUG_LED             7    // GPIO7  -> DEBUG_LED (R6 220Ω)
    #define PIN_NEOPIXEL              8    // GPIO8  -> WS2812 LED_OUT

    // I2C bus
    #define PIN_SDA                   2    // GPIO2  -> SDA (10K pullup)
    #define PIN_SCL                   8    // GPIO8  -> SCL (10K pullup) *** SHARED ***

    // Power gating
    #define PIN_5V_EXT_EN             20   // RXD0  -> 5V_EXT_EN
    #define PIN_BOOT_BUTTON           9    // GPIO9  -> BOOT (strapping)

    #define NUM_DRIVE_MOTORS          2
    #define HAS_IMU                   1
    #define HAS_NEOPIXEL              1

#else
    #error "Unknown BOARD_REV. Define as 2 (v2 production) or 3 (v3 next rev)."
#endif

// ---- Compile-time sanity checks ----

// These checks fail the build if the pins are obviously wrong.
// They catch the common copy-paste errors that bit v1.3.

// Boot button MUST be on a strapping pin (GPIO9 on ESP32-C3).
#if PIN_BOOT_BUTTON != 9
    #error "PIN_BOOT_BUTTON must be GPIO9 (the ESP32-C3 strapping pin)."
#endif

// Battery ADC MUST be on an ADC-capable pin.
#if PIN_BATT_MEAS != 3
    #error "PIN_BATT_MEAS must be GPIO3 (ADC1_CH3 on ESP32-C3)."
#endif

// Drive motor pins must be unique.
#if (PIN_MOTOR1_IN1 == PIN_MOTOR1_IN2) || \
    (PIN_MOTOR1_IN1 == PIN_MOTOR2_IN1) || \
    (PIN_MOTOR1_IN1 == PIN_MOTOR2_IN2) || \
    (PIN_MOTOR1_IN2 == PIN_MOTOR2_IN1) || \
    (PIN_MOTOR1_IN2 == PIN_MOTOR2_IN2) || \
    (PIN_MOTOR2_IN1 == PIN_MOTOR2_IN2)
    #error "Drive motor pins must all be different."
#endif

// ---- Board info struct (for runtime introspection) ----

struct BoardInfo {
    const char* name;
    const char* revision;
    uint8_t num_drive_motors;
    bool has_drum;
    bool has_imu;
    bool has_neopixel;
    int pin_motor1_in1;
    int pin_motor1_in2;
    int pin_motor2_in1;
    int pin_motor2_in2;
    int pin_servo1;
    int pin_servo2;
    int pin_drum_pwm;
    int pin_batt_meas;
    int pin_mode_button;
    int pin_debug_led;
    int pin_neopixel;
    int pin_sda;
    int pin_scl;
    int pin_5v_ext_en;
    int pin_boot_button;
};

inline constexpr BoardInfo kBoardInfo = {
    BOARD_NAME,
    BOARD_REVISION_STRING,
    NUM_DRIVE_MOTORS,
    HAS_DRUM ? true : false,
    HAS_IMU ? true : false,
    HAS_NEOPIXEL ? true : false,
    PIN_MOTOR1_IN1,
    PIN_MOTOR1_IN2,
    PIN_MOTOR2_IN1,
    PIN_MOTOR2_IN2,
    PIN_SERVO1,
    PIN_SERVO2,
    PIN_DRUM_PWM,
    PIN_BATT_MEAS,
    PIN_MODE_BUTTON,
    PIN_DEBUG_LED,
    PIN_NEOPIXEL,
    PIN_SDA,
    PIN_SCL,
    PIN_5V_EXT_EN,
    PIN_BOOT_BUTTON,
};

// Compile-time diagnostic: when this header is included, log which board
// is being targeted. Useful for build output.
#ifdef BOARD_CONFIG_VERBOSE
    #pragma message "Building for " BOARD_NAME " (" BOARD_REVISION_STRING ")"
#endif