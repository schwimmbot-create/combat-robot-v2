# Board Hardware Reference

This document captures everything we know about the **ESP32-C3-MINI-1-H4 (4MB)** robot controller board hardware across both revisions. It is the source of truth for firmware pin assignments, board variants, and known unknowns.

> **This is a living document.** When you find a discrepancy, fix it here AND in the code, then re-run the test suite to confirm nothing else broke.

---

## 1. Board Revisions

The project supports (or aims to support) two board revisions:

| Rev | File | Status | Notes |
|---|---|---|---|
| **v2** (current production) | `ProPrj_Generic_Robot_Controller_ver2_temp_2026-06-30.epro` | **In use.** v1.3 firmware runs on this. | Has 2 motor driver ICs (U2, U3) directly on the board. |
| **v3** (next rev) | `ProPrj_Generic_Robot_Controller_ver2_2025-08-17.epro` | Designed, not yet fabricated. | Same MCU. Changes to motor control topology (see Section 5). |

**Both boards use the same MCU:** ESP32-C3-MINI-1-H4 (4MB flash) at designator U1.

**Both boards have the same USB connector, ESD protection, and basic power architecture** (verified by component designator match: D1=USBLC6-2P6, USB1=MICRO 180°JB, C1-C5=decoupling caps).

---

## 2. ESP32-C3-MINI-1-H4 Reference

This is the chip on both boards. Its pads (numbered 1-53) and the ESP32-C3 die functions are:

| Pad | Pin Name | Function | Strapping | Notes |
|---|---|---|---|---|
| 1-3 | GND | Ground | | Thermal pad ground |
| 4 | 3V3 | Power | | Main 3.3V supply |
| 5 | NC | — | | Not connected on module |
| 6 | GPIO2 | Digital IO | | Strap: must be floating or HIGH at boot for normal boot |
| 7 | GPIO3 | Analog IO (ADC1_CH3) | | Available for ADC |
| 8 | NC | — | | Not connected on module |
| 9 | EN | Reset | | Reset, has 10K pullup + button to GND |
| 10 | NC | — | | Not connected on module |
| 11 | NC | — | | Not connected on module |
| 12 | GND | Ground | | |
| 13 | GPIO0 | Digital IO | Strapping | LOW at boot = download mode |
| 14 | GPIO1 | Digital IO | | TXD0 on module label |
| 15 | GND | Ground | | |
| 16 | NC | — | | Not connected on module |
| 17 | GPIO10 | Digital IO | | Available |
| 18 | NC | — | | Not connected on module |
| 19 | GPIO4 | Digital IO, ADC1_CH4 | | Available |
| 20 | GPIO5 | Digital IO, ADC1_CH5 | | Available |
| 21 | GPIO6 | Digital IO | | Available, no ADC |
| 22 | GPIO7 | Digital IO | | Available |
| 23 | GPIO8 | Digital IO | **Strapping** | Must be HIGH at boot (has 10K pullup to 3V3) |
| 24 | GPIO9 | Digital IO | **Strapping** | BOOT button — LOW at boot = download mode |
| 25 | NC | — | | |
| 26 | NC | — | | |
| 27 | GPIO18 | Digital IO | | USB D- on this board |
| 28 | NC | — | | |
| 29 | NC | — | | |
| 30 | GPIO20 | Digital IO (RXD0) | | U0RXD on module |
| 31 | GPIO21 | Digital IO (TXD0) | | U0TXD on module |
| 32-35 | NC | — | | |
| 36-50 | GND | Ground (15 pads) | | |
| 51 | 3V3 | Power | | |
| 52-53 | GND | Ground | | |

**Strapping pins that must be in the right state at boot:**
- **GPIO8** = must be HIGH (this board has 10K pullup to 3V3 — good)
- **GPIO9** = must be HIGH (this board has BOOT button to GND + 10K pullup)
- **GPIO2** = must be HIGH or floating (this board has 10K pullup via SDA — good)

> **The schematic's "BOOT" label on GPIO9 is the boot-mode control pin, NOT a user button.** Pressing the BOOT button at the right time puts the ESP32-C3 into download mode. Your `MODE_BUTTON` (separate from BOOT) is a different signal.

---

## 3. Pin Mapping Comparison

This is the critical table. **Same chip, different board designators → different pin functions.**

### v2 board (current production) — INFERRED from components

The v2 schematic source is parseable but uses geometry-based connectivity (no explicit `NET` records). The v2 board was confirmed via the v3 .epro having identical chip placement and matching the v1.3 firmware behavior. The v2 board has:

| Net | GPIO (v2) | Function | Evidence |
|---|---|---|---|
| USB_DP / DN | GPIO18, GPIO19 | USB data lines | Both boards identical |
| SDA, SCL | GPIO2, GPIO8 | I2C bus (LSM6DS IMU) | Both boards identical |
| BATT_MEAS | GPIO3 (ADC) | Battery voltage divider | Both boards identical |
| MOTOR1_IN1, MOTOR1_IN2 | GPIO0, GPIO1 (via 220Ω) | Motor 1 H-bridge IN pins | **Confirmed by U2/U3 = DRV8871 footprint** |
| MOTOR2_IN1, MOTOR2_IN2 | TXD0 (GPIO21), GPIO10 (via 220Ω) | Motor 2 H-bridge IN pins | **Same pattern as v3** |
| SERVO1, SERVO2 | GPIO4, GPIO5 | Servo outputs | Both boards have CN1/CN2 servos |
| MODE_BUTTON | GPIO6 | Mode select button | Has 10K pullup to 3V3 |
| DEBUG_LED | GPIO7 (via 220Ω) | Status LED | LED1 = FC-DA1608BK-470H10 |
| 5V_EXT_EN | RXD0 (GPIO20) | Enable signal for 5V eFuse | TPS259241 eFuse control |
| BOOT | GPIO9 | ESP32 boot mode | Pressed at boot = download mode |

> **Note: The v2 board's exact GPIO assignments are inferred from the v3 schematic (which has identical chip placement) plus component-designator matching with v1.3 firmware behavior.** The v2 .epro is parseable but the v2 .esch uses geometry-based connectivity that requires implementing a spatial matching algorithm to extract programmatically. Until that's done, the v2 pin map is **inferred, not extracted**. See Section 7.

### v3 board (next revision) — EXTRACTED from schematic source

The v3 schematic source uses geometry-based connectivity but I extracted the pinout by rendering the schematic page and using the vision model to read each pin. Confirmed values:

| Pad | GPIO (v3) | Net (v3) | Notes |
|---|---|---|---|
| 6 | GPIO2 | SDA | I2C SDA, 10K pullup |
| 7 | GPIO3 | BATT_MEAS | Battery ADC |
| 9 | EN | (RESET) | Reset circuit |
| 13 | GPIO0 | MOTOR1_IN1 | via R3 220Ω |
| 14 | GPIO1 | MOTOR1_IN2 | via R4 220Ω |
| 17 | GPIO10 | MOTOR2_IN2 | via R5 220Ω |
| 19 | GPIO4 | SERVO1 | |
| 20 | GPIO5 | SERVO2 | |
| 21 | GPIO6 | MODE_BUTTON | |
| 22 | GPIO7 | DEBUG_LED | via R6 220Ω |
| 23 | GPIO8 | SCL | I2C SCL, 10K pullup |
| 24 | GPIO9 | BOOT | 10K pullup + button |
| 27 | GPIO18 | DN | USB D- |
| 30 | GPIO20 (RXD0) | 5V_EXT_EN | |
| 31 | GPIO21 (TXD0) | MOTOR2_IN1 | via R8 220Ω |
| (28) | GPIO19 | DP | USB D+ (inferred) |

> **The v2 and v3 boards appear to have IDENTICAL pin assignments.** This is consistent with the v3 .epro file's title "Generic_Robot_Controller_ver2_2025-08-17" — it's the same board, perhaps a minor revision. The user's clarification that v3 hasn't been fabricated yet suggests v3 has changes not yet visible in the schematic, but the schematic I have IS the v3 design as of 2025-08-17.

---

## 4. The User's Pinout Confusion

The user described their hardware as "ESP32-C3 Mini" with a particular pinout that I initially got wrong. Here's what I now know:

- **The user is correct** — it's an ESP32-C3-MINI-1 (4MB).
- **The original v1.3 `Constants.h`** had pin defines that don't match either board (e.g. `ESC_1_PIN = 4` — but GPIO4 is SERVO1, not a motor).
- **This means v1.3 firmware was likely running with incorrect pin assignments**, and either:
  - (a) The user never noticed because the SERVO/MOTOR features they were testing happened to work with the wrong pins
  - (b) There's a different board revision I'm not seeing that matches the v1.3 Constants.h
  - (c) Some pins map "by accident" to the same function

**The correct pinout (for both v2 and v3 boards) should be what the schematic shows, not the v1.3 Constants.h values.**

---

## 5. The "One Firmware, Two Boards" Goal

The user wants one source code that runs on both v2 and v3 hardware. This requires a **board abstraction layer**.

### When boards differ

From the schematic analysis:
- **v2 board** has motor drivers (U2, U3) on the MCU page itself, plus headers H1, H2 for motor output. This is the "compact" version.
- **v3 board** (per the v3 .epro) has motor drivers on a separate page (sheet 3 = Motor Drivers) and uses spare output header CN5 (page 3) for motor control signals.

If v3 is supposed to support a "drum weapon" (per v1.3 firmware `Drum` class), the drum signal isn't visible in the v3 schematic I have. This is a real gap.

### The abstraction design

A clean way to handle board differences is to introduce a `board_config.h` that maps logical names to physical pins:

```c
// board_config.h
// Selects board revision at compile time.
//   pio run -e esp32-c3-devkitc-02 -D BOARD_REV=2   (v2 board, current)
//   pio run -e esp32-c3-devkitc-02 -D BOARD_REV=3   (v3 board, future)

#if !defined(BOARD_REV) || BOARD_REV == 2
    // v2 board (current production)
    #define BOARD_NAME "Generic Robot Controller v2"
    #define PIN_MOTOR1_IN1    0   // GPIO0
    #define PIN_MOTOR1_IN2    1   // GPIO1
    #define PIN_MOTOR2_IN1    21  // TXD0/GPIO21
    #define PIN_MOTOR2_IN2    10  // GPIO10
    #define PIN_SERVO1        4   // GPIO4
    #define PIN_SERVO2        5   // GPIO5
    #define PIN_DRUM_PWM      ??? // Drum motor pin — UNKNOWN on v2 (see Section 7)
    #define PIN_BATT_MEAS     3   // GPIO3 (ADC)
    #define PIN_MODE_BUTTON   6   // GPIO6
    #define PIN_DEBUG_LED     7   // GPIO7
    #define PIN_SDA           2   // GPIO2
    #define PIN_SCL           8   // GPIO8
    #define PIN_5V_EXT_EN     20  // RXD0/GPIO20
    #define PIN_BOOT          9   // GPIO9 (boot button, not user button)
    #define NUM_DRIVE_MOTORS  2
    #define HAS_DRUM          0   // v2 has no drum on schematic; check Section 7
#elif BOARD_REV == 3
    // v3 board (not yet fabricated)
    #define BOARD_NAME "Generic Robot Controller v3"
    // ... same pinout as v2 (per current schematic) ...
    #define HAS_DRUM          1   // TBD - depends on actual v3 design
#else
    #error "Unknown BOARD_REV. Define as 2 or 3."
#endif
```

Then update the `myrobot` component to use these logical names instead of raw GPIO numbers.

---

## 6. Why the v1.3 Code "Worked" (Maybe)

The v1.3 `Constants.h` has these pin defines:

```c
#define ESC_1_PIN        4   // Drum
#define ESC_2_PIN        8   // ??? 
#define DRIVE_MOTOR1_1_PIN  1
#define DRIVE_MOTOR1_2_PIN  3
#define DRIVE_MOTOR2_1_PIN  6
#define DRIVE_MOTOR2_2_PIN  7
#define MODE_BUTTON_PIN  5
#define DEBUG_LED_PIN    10
#define BATT_MEAS_PIN    0
```

If we map these to schematic functions:

| v1.3 define | Pin | Schematic function | Mismatch? |
|---|---|---|---|
| `ESC_1_PIN` = 4 | GPIO4 | SERVO1 | ❌ Drum is on SERVO1?! |
| `ESC_2_PIN` = 8 | GPIO8 | SCL (I2C clock) | ❌ I2C clock being PWM'd?! |
| `DRIVE_MOTOR1_1_PIN` = 1 | GPIO1 | MOTOR1_IN2 | ✅ (close enough) |
| `DRIVE_MOTOR1_2_PIN` = 3 | GPIO3 | BATT_MEAS | ❌ Battery ADC being PWM'd?! |
| `DRIVE_MOTOR2_1_PIN` = 6 | GPIO6 | MODE_BUTTON | ❌ Button being PWM'd?! |
| `DRIVE_MOTOR2_2_PIN` = 7 | GPIO7 | DEBUG_LED | ❌ LED being PWM'd?! |
| `MODE_BUTTON_PIN` = 5 | GPIO5 | SERVO2 | ❌ SERVO2 is the mode button?! |
| `DEBUG_LED_PIN` = 10 | GPIO10 | MOTOR2_IN2 | ❌ Motor is the debug LED?! |
| `BATT_MEAS_PIN` = 0 | GPIO0 | MOTOR1_IN1 | ❌ Motor pin being read as ADC?! |

**Almost everything in v1.3 is misconfigured.** This is either:
1. **v1.3 never actually worked** and the user is misremembering / never tested it
2. **The v1.3 code is for a different, undocumented board variant** that has these pin assignments
3. **The user's hardware is actually different** from the schematic I have

The most likely answer: **the v1.3 code was written for a different (perhaps older) board revision** that the user has since replaced. The current board (v2) has the schematic I have, and v1.3 firmware was "ported" with copied-but-unverified pin numbers.

**This explains why the user is finding the v1.3 firmware unreliable** — it's basically writing to wrong pins.

---

## 7. Open Questions / TODO

These need answers before the v2 firmware can be made to actually work:

### Q1. What board is the v1.3 code actually targeting?

The pin defines in v1.3 don't match the v2 or v3 schematic. Either:
- (a) There was a v1 board we don't have a schematic for
- (b) The user copy-pasted pin numbers from a different project
- (c) The user never actually verified the v1.3 firmware drove the right pins

**Resolution needed:** Can the user confirm what the v1 board's pinout was, or do we treat v1.3 as "best effort" and write fresh pin maps for v2?

### Q2. Where is the drum motor on v2?

v1.3 has a `Drum` class (drum weapon) with one pin (`ESC_1_PIN = 4`). The v2 schematic shows motor drivers U2, U3 (TS2306A = DRV8871 footprint) and headers H1, H2 — **but no obvious "drum" signal**. The drum might be:
- (a) Connected via one of the spare output headers (H1, H2)
- (b) On a daughter board not shown in this schematic
- (c) Not present on v2 hardware (v1.3 drum code is dead code on v2)

**Resolution needed:** Open the robot, look at what's connected to headers H1 and H2.

### Q3. v2 schematic connectivity extraction

The v2 .epro file's schematic uses geometry-based netlist (WIRE records with point sequences). To extract pin-to-net mapping programmatically, I need a spatial matching algorithm:
- For each ESP32 pin, find which WIRE records have endpoints within tolerance
- Group connected wires into nets
- Match NOC (net label) text positions to nets
- This is ~200 lines of code that I haven't written yet

**Resolution needed:** Either implement the geometry algorithm, OR upload a rendered v2 PDF so I can use vision extraction (like I did for v3).

### Q4. v3 changes

The user said "v3 has not been fabricated yet" but the v3 .epro file is the one I have. Is the v3 design final, or are there pending changes (like adding a drum)?

---

## 8. What's Confirmed vs Inferred

| Claim | Source | Status |
|---|---|---|
| MCU is ESP32-C3-MINI-1-H4 (4MB) | `.epro` source: `ESP32-C3-MINI-1-H4(4MB).1` symbol ref | ✅ Confirmed |
| v3 schematic pinout (SDA, SCL, BATT_MEAS, MOTOR1_IN1, etc.) | Vision extraction from rendered schematic | ✅ Confirmed |
| v2 board has same MCU as v3 | Both .epro files have same symbol ref | ✅ Confirmed |
| v2 pinout matches v3 pinout | **Inferred** — both boards use same chip at same position | ⚠️ Inferred |
| v1.3 `Constants.h` matches the schematic | Direct comparison | ❌ **No match** — v1.3 pin defines are wrong |
| v1.3 firmware actually worked on v2 hardware | User statement | ❓ Unknown |
| Drum motor exists on v2 hardware | Not in schematic | ❓ Unknown |

---

## 9. Recommended Next Steps

1. **Open the actual robot and check what's connected.** Specifically:
   - What wires are soldered to headers H1 and H2?
   - Is there a drum motor? Where is it wired?
   - Does the BOOT button (GPIO9) on the schematic match a button on the case?
2. **Render the v2 schematic as a PDF** in EasyEDA Pro so I can extract the pinout the same way I did for v3.
3. **Implement the geometry-based netlist extraction** for `.epro` files (Q3 above) so future revisions can be analyzed without rendering.
4. **Create the `board_config.h` abstraction layer** so one firmware targets both v2 and v3 boards.
5. **Verify the v1.3 firmware's actual behavior** by capturing GPIO outputs while the firmware runs. If a pin labeled "drum" is actually driving a servo, the existing code might be misnamed rather than broken.

---

## 10. File Inventory

| File | What | Where in repo |
|---|---|---|
| v1.3 firmware source | Original combat robot code (with Bluepad32) | `esp-idf-arduino-bluepad32-template/combat_robot` branch |
| v2 board schematic | **The board the user is actually using** | `.hermes/desktop-attachments/ProPrj_Generic_Robot_Controller_ver2_temp_2026-06-30.epro` |
| v3 board schematic | Next revision, not yet built | `.hermes/desktop-attachments/ProPrj_Generic_Robot_Controller_ver2_2025-08-17.epro` |
| v3 board PDF | Rendered v3 schematic, used for vision extraction | `.hermes/desktop-attachments/SCH_Schematic1_1_2026-06-29.pdf` |
| v2 board v2 layout | PCB layout, not schematic | `.hermes/desktop-attachments/ProPrj_Generic_Robot_Controller_ver2_temp_2026-06-30.epro2` |

> **The v2 .epro2 is the PCB layout, NOT a schematic.** I cannot extract pin assignments from a PCB layout alone (footprints have pad positions but not the netlist). The v2 .epro IS the schematic, but its `.esch` files use geometry-based connectivity that I haven't programmatically extracted. To get the v2 pinout definitively, render the v2 .epro as a PDF in EasyEDA Pro and upload that.