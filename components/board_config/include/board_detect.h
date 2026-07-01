// board_detect.h — Board revision selection (NVS override only)
//
// Purpose: let one compiled binary run on either v2 or v3 hardware
// by storing the active revision in NVS flash. The web UI exposes a
// "Set Board Revision" endpoint that writes the override.
//
// Why NVS override only (not hardware strapping)?
//   - No board modification required. You can swap boards by changing
//     a setting in the web UI.
//   - The v3 board isn't fabricated yet. We don't know which GPIOs
//     will be free for strapping pads until the design is final.
//   - One-time setup: ask the user once via the web UI, persist in NVS.
//
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <stdint.h>
#include "esp_err.h"
#include "board_config.h"

// ---- Detection API ----

// Board ID values (1 byte for now; can extend to 2 bytes for 16+ revs).
// Mirrors the BoardRevId enum from the previous design.
enum BoardRevId : uint8_t {
    BOARD_REV_ID_UNKNOWN = 0x00,
    BOARD_REV_ID_V2      = 0x02,
    BOARD_REV_ID_V3      = 0x03,
};

// Read the active board revision. Priority:
//   1. NVS override (if user set it via web UI)
//   2. Compile-time default (from -DBOARD_REV=N)
// Returns the integer rev (2, 3, etc.) or 0 if unknown.
int board_detect_active_rev(void);

// Convert a BoardRevId to the corresponding BOARD_REV integer value
// (2, 3, etc.) so existing #if BOARD_REV == N code works at runtime.
int board_detect_id_to_rev(BoardRevId id);

// NVS override API (used by web UI)

// Set a board revision override in NVS. Takes effect on next boot.
// rev should be 2, 3, etc.
esp_err_t board_detect_set_override(int rev);

// Clear the NVS override. The active rev will fall back to compile-time.
esp_err_t board_detect_clear_override(void);

// Check if a NVS override is currently set. Returns true/false.
// (out_rev is set to the override value if true is returned.)
bool board_detect_has_override(int *out_rev);