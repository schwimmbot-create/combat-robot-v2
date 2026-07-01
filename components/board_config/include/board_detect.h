// board_detect.h — Runtime board revision detection
//
// Goal: when the firmware boots, figure out which board revision it's
// running on so it can auto-configure pins without needing -DBOARD_REV=N
// at compile time.
//
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <stdint.h>
#include "board_config.h"

// ---- How this works ----
//
// We use 1-3 GPIO strapping pins as board ID inputs. Each board revision
// pulls these pins to a specific combination of HIGH/LOW via onboard
// resistors. The firmware reads the pins at boot and selects the
// matching BOARD_REV.
//
// Advantages:
//   * Zero ongoing cost (one ADC read at boot, then done)
//   * Survives reflashing (stored in hardware, not NVS)
//   * User can't get it wrong
//   * Extensible to v4, v5, etc. with more pins
//
// Disadvantages:
//   * Requires board modification (add 2-3 resistor pads per board rev)
//   * Uses GPIO pins (need to find ones not used by other peripherals)
//
// ---- Hardware design ----
//
// Use 2 free GPIOs as BOARD_ID0 and BOARD_ID1. Wire as follows:
//
// Board v2: BOARD_ID0 = GND (0), BOARD_ID1 = GND (0)  -> reads 0b00
// Board v3: BOARD_ID0 = GND (0), BOARD_ID1 = 3V3 (1)  -> reads 0b01
// Board v4: BOARD_ID0 = 3V3 (1), BOARD_ID1 = GND (0)  -> reads 0b10 (future)
// Board v5: BOARD_ID0 = 3V3 (1), BOARD_ID1 = 3V3 (1)  -> reads 0b11 (future)
//
// Resistors: 10K pull-up to 3V3 on each ID pin (built-in to ESP32-C3
// is fine), then on each board revision either tie to GND (0) or leave
// floating (1) — or vice versa.
//
// IMPORTANT: Use GPIOs that:
//   * Are NOT strapping pins (don't affect boot mode)
//   * Are NOT used by other peripherals (motors, LEDs, etc.)
//   * Have input-capable pads on the ESP32-C3-MINI-1 module
//
// Looking at board_config.h, the used GPIOs on both boards are:
// 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 18, 19, 20, 21
//
// Free GPIOs available on the C3-MINI-1 module: GPIO11-GPIO17 (pads 5, 8,
// 10, 11, 16, 18, 22 if not NC; need to check the actual module pinout).
// However, the v2/v3 schematic shows them as NC (not connected to anything
// on the board) so they're available for board ID use.
//
// PICK: BOARD_ID0 = GPIO11, BOARD_ID1 = GPIO12 (if both are NC on the
// board; if not, choose different free GPIOs from the module pinout).

#ifndef BOARD_ID_GPIO0
#  if BOARD_REV == 2 || BOARD_REV == 3
#    define BOARD_ID_GPIO0  11   // Wire to GND on v2, 3V3 on v3
#    define BOARD_ID_GPIO1  12   // Wire to GND on v2, GND on v3 (no change)
#  else
#    define BOARD_ID_GPIO0  255  // Invalid
#    define BOARD_ID_GPIO1  255
#  endif
#endif

// ---- Detection API ----

// Board ID values (1 byte for now; can extend to 2 bytes for 16+ revs)
enum BoardRevId : uint8_t {
    BOARD_REV_ID_UNKNOWN = 0x00,
    BOARD_REV_ID_V2      = 0x02,
    BOARD_REV_ID_V3      = 0x03,
    // BOARD_REV_ID_V4 = 0x04, etc.
};

// Read the BOARD_ID pins and return the detected board revision.
// Returns BOARD_REV_ID_UNKNOWN if the pins don't match any known board.
//
// IMPORTANT: This function is called BEFORE any other GPIO init. The
// caller must configure the ID pins as inputs with internal pull-ups
// enabled, then read the levels.
BoardRevId board_detect_read_id(void);

// Convert a BoardRevId to the corresponding BOARD_REV macro value
// (2, 3, etc.) so existing #if BOARD_REV == N code works.
int board_detect_id_to_rev(BoardRevId id);

// Get the active BOARD_REV at runtime. This is the value to use for
// all runtime conditional logic that can't use compile-time #if.
//
// The value is determined by:
//   1. The compile-time BOARD_REV (from -DBOARD_REV=N)
//   2. The runtime detection (if board_detect_init() was called)
//   3. NVS override (if user set it via web UI)
//
// If all three disagree, the priority is: NVS > runtime detect > compile-time.
int board_detect_active_rev(void);

// Initialize detection. Call this early in app_main() before any other
// GPIO init. Reads the strapping pins and stores the result.
//
// The detected rev is logged via ESP_LOGI. If detection fails (no matching
// board found), falls back to the compile-time BOARD_REV and logs a warning.
void board_detect_init(void);