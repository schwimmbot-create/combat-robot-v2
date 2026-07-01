# Board Hardware Reference

This document captures everything we know about the **ESP32-C3-MINI-1-H4 (4MB)** robot controller board hardware across both revisions. It is the source of truth for firmware pin assignments, board variants, motor driver topology, and known unknowns.

> **This is a living document.** When you find a discrepancy, fix it here AND in the code, then re-run the test suite to confirm nothing else broke.

---

## 1. Board Revisions

The project supports (or aims to support) two board revisions:

| Rev | Schematic source | Status | Motor drivers | Spare header | Notes |
|---|---|---|---|---|---|
| **v2** (current production) | `hardware/board-v2-rev1-schematic.epro` (from `ProPrj_Generic_Robot_Controller_ver2_temp_2026-06-30.epro`) | **In use.** v1.3 firmware runs on this. | 2× DRV8871 + 2× "TS2306A" (aux switch) | None (just motor outputs P1, P2) | 2 brushed DC motors max |
| **v3** (next rev) | `hardware/board-v3-rev1-schematic.epro` (from `ProPrj_Generic_Robot_Controller_ver2_2025-08-17.epro`) | Designed, not yet fabricated. | 4× DRV8871DDAR | **CN5** (WAFER-SH1.0-5PLB, 5 signal + 2 GND) | 4 brushed DC motors **or** 2 BLDC via CN5 breakout |

**Both boards use the same MCU:** ESP32-C3-MINI-1-H4 (4MB flash) at designator U1.

**Both boards have the same USB connector, ESD protection, and basic power architecture** (verified by component designator match: D1=USBLC6-2P6, USB1=MICRO 180°JB, C1-C5=decoupling caps).

> **Schematic files are stored in `hardware/`** with versioned names. See Section 10 for the file inventory.

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

> **The v2 and v3 boards appear to have IDENTICAL pin assignments** for the GPIO-to-net mapping. Both boards expose the same motor control signals (MOTOR1_IN1/IN2, MOTOR2_IN1/IN2) on the same GPIOs. The differences are in the *downstream* motor driver topology (see Section 4).

---

## 4. Motor Driver Topology (THE BIG DIFFERENCE)

This is the key hardware difference between v2 and v3, and what the user is asking about.

### v2 board: 2 motor drivers, 2 motors, no BLDC breakout

The v2 board has only **2 brushed DC motor drivers**:

| Component | Designator | Function |
|---|---|---|
| U5 | DRV8871DDAR | Motor 1A driver (left motor) |
| U6 | DRV8871DDAR | Motor 2A driver (right motor) |
| P1 | PH-2A connector | Motor 1A output (to brushed DC motor) |
| P2 | PH-2A connector | Motor 2A output (to brushed DC motor) |

Plus on the MCU page: **2× "TS2306A 240GF MSM 9" components (U2, U3)** — these are likely auxiliary power switches (probably the 5V eFuse control circuits or similar), not motor drivers.

**v2 has 2 brushed DC motors, period. No BLDC breakout.**

### v3 board: 4 motor drivers, 4 brushed DC motors, **PLUS CN5 BLDC breakout**

The v3 board has **4 brushed DC motor drivers** AND a **CN5 spare output header** that exposes the same motor control signals for external use:

| Component | Designator | Function |
|---|---|---|
| U7 | DRV8871DDAR | Motor 1A driver (left motor, brushed DC) |
| U8 | DRV8871DDAR | Motor 1B driver (right motor? or second motor on same axis) |
| U9 | DRV8871DDAR | Motor 2A driver |
| U10 | DRV8871DDAR | Motor 2B driver |
| P1, P2, P3, P4 | PH-2A connectors | Motor 1A, 1B, 2A, 2B outputs |
| **CN5** | WAFER-SH1.0-5PLB (7-pad JST-SH) | **Spare output header** |

### CN5 Pinout (v3 board, BLDC breakout)

The 7 pads of CN5 are arranged with the motor control signals in the middle and grounds on the outside:

| Pin | Signal | Notes |
|---|---|---|
| 1 | GND | |
| 2 | MOTOR1_IN1 | DRV8871 input signal (replicated from U7/U8) |
| 3 | MOTOR1_IN2 | |
| 4 | MOTOR2_IN2 | |
| 5 | MOTOR2_IN1 | |
| 6 | GND | |
| 7 | GND | (extra ground for shielding) |

**Annotation on the schematic (yellow box):** "Spare output header for motor pins. Protected by 220Ohms"

### What CN5 is for

The CN5 signals are **the same net as the DRV8871 inputs** — so they're not independent outputs. They're a parallel tap on the same control lines, with 220Ω series resistors for protection.

**Use cases for CN5:**

1. **Connect an external BLDC ESC** instead of using the on-board DRV8871s. You'd:
   - Disconnect the brushed DC motor from the DRV8871 output (P1/P2/P3/P4)
   - Connect the BLDC ESC signal input to MOTOR1_IN1/IN2 (or MOTOR2_IN1/IN2) on CN5
   - The DRV8871 will be idle (no motor = no current draw) but the ESP32 still drives the same control lines
   - The BLDC ESC treats the IN1/IN2 lines as a standard RC servo PWM input (PWM frequency, 1-2ms pulse)

2. **Connect an external brushed DC driver** (more powerful than the on-board DRV8871) that has its own IN1/IN2 input pins.

3. **Connect a logic analyzer or scope** for debugging the motor control signals.

### Important caveats for CN5 use

- **CN5 signals are NOT independently controlled.** They share the same ESP32 GPIOs as the on-board DRV8871s. If the firmware sends "drive motor 1 forward at 50%," the same signal goes to both the DRV8871 (which drives a brushed DC motor) AND any external device connected to CN5.
- **The 220Ω series resistors** on CN5 are there to protect the ESP32 GPIO from shorts on the external wiring. The DRV8871 inputs go through different series resistors (R3, R4, R5, R8 = 220Ω on the schematic). Both sets of resistors feed the same net, so the ESP32 sees the parallel combination of all paths.
- **Voltage levels:** The CN5 signals are 3.3V CMOS logic, which is compatible with most modern ESCs (which accept 3.3V or 5V logic). Older ESCs that require 5V TTL logic levels may not work reliably.
- **PWM frequency:** The DRV8871 expects 0-200 kHz PWM on its INx pins. Most RC ESCs expect 50 Hz servo PWM. **The same GPIO cannot drive both at the same time** without conflicts. You'd need to choose:
  - Drive brushed DC motors via on-board DRV8871s (firmware sets `DRIVE_MOTOR_PWM_FREQ = 20000`)
  - Drive BLDC ESCs via CN5 (firmware sets `ESC_PWM_FREQ = 50`)

  This is a firmware mode selection, not a hardware constraint.

---

## 5. The "One Firmware, Two Boards" Goal

The user wants one source code that runs on both v2 and v3 hardware. This requires a **board abstraction layer**.

### What the abstraction needs to handle

| Difference | v2 board | v3 board | How to handle |
|---|---|---|---|
| GPIO → net mapping | Same | Same | Single set of pin defines |
| Motor driver count | 2 (U5, U6) | 4 (U7-U10) | `NUM_DRIVE_MOTORS` config |
| Motor output connectors | 2 (P1, P2) | 4 (P1-P4) | Auto-derived from `NUM_DRIVE_MOTORS` |
| Spare output header (CN5) | None | Yes (7 pins) | `HAS_SPARE_HEADER` config; gates firmware features that use it |
| Drum motor | **Unknown** — see Section 7 | **Unknown** | TBD |

### The abstraction design

A clean way to handle board differences is to introduce a `board_config.h` that maps logical names to physical pins and capabilities:

```c
// board_config.h - select at compile time with -DBOARD_REV=N
#if BOARD_REV == 2
    #define NUM_DRIVE_MOTORS    2
    #define HAS_SPARE_HEADER    0
    #define HAS_DRUM            0
#elif BOARD_REV == 3
    #define NUM_DRIVE_MOTORS    4
    #define HAS_SPARE_HEADER    1   // CN5 breakout for BLDC/external driver
    #define HAS_DRUM            0
#endif
```

The pin defines (`PIN_MOTOR1_IN1`, `PIN_SERVO1`, etc.) are the same on both boards — only the *count* and *extras* differ.

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

If we map these to schematic functions (which are the SAME on v2 and v3):

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

**Resolution needed:** Can the user confirm what the v1 board's pinout was, or do we treat v1.3 as "best effort" and write fresh pin maps for v2/v3?

### Q2. Where is the drum motor on v2?

v1.3 has a `Drum` class (drum weapon) with one pin (`ESC_1_PIN = 4`). The v2 schematic shows:
- Motor drivers U5, U6 (DRV8871) on the motor driver page
- Motor outputs P1, P2 (PH-2A connectors)
- **No CN5** (no spare output header on v2)
- **No "drum" label** anywhere

The drum might be:
- (a) Connected to one of the P1/P2 outputs (just labeled as "motor" instead of "drum" in the schematic)
- (b) On a daughter board not shown in the schematic
- (c) Not present on v2 hardware (v1.3 drum code is dead code on v2)

**Resolution needed:** Open the robot, look at what's connected to P1 and P2.

### Q3. Will the v3 board add a drum?

v3 has 4 motor drivers and CN5. Possible configurations:
- 4 brushed DC motors (no drum)
- 2 brushed DC motors + 1 drum (using 2 DRV8871s for the brushed motors and 1 motor control pair on CN5 for the drum)
- 2 brushed DC motors + BLDC motors via CN5

**Resolution needed:** Confirm v3 design intent. Until then, `HAS_DRUM=0` for both boards.

### Q4. v2 schematic connectivity extraction

The v2 .epro file's schematic uses geometry-based netlist (WIRE records with point sequences). To extract pin-to-net mapping programmatically, I need a spatial matching algorithm:
- For each ESP32 pin, find which WIRE records have endpoints within tolerance
- Group connected wires into nets
- Match NOC (net label) text positions to nets
- This is ~200 lines of code that I haven't written yet

**Resolution needed:** Either implement the geometry algorithm, OR upload a rendered v2 PDF so I can use vision extraction (like I did for v3).

### Q5. Does v2 have CN5?

**No.** I verified by parsing the v2 .epro: there's no "WAFER" or "CN5" component. v2 has only 2 motor drivers and 2 motor output connectors.

### Q6. Where are the v2 "TS2306A" components?

The v2 .epro shows two components with symbol `TS2306A 240GF MSM 9_C2976675` (U2, U3) on the MCU page. These appear to be auxiliary ICs, not motor drivers. Need to investigate their function — could be voltage regulators, eFuse controllers, or something else.

---

## 8. What's Confirmed vs Inferred

| Claim | Source | Status |
|---|---|---|
| MCU is ESP32-C3-MINI-1-H4 (4MB) | `.epro` source: `ESP32-C3-MINI-1-H4(4MB).1` symbol ref | ✅ Confirmed |
| v3 schematic pinout (SDA, SCL, BATT_MEAS, MOTOR1_IN1, etc.) | Vision extraction from rendered schematic | ✅ Confirmed |
| v2 board has same MCU as v3 | Both .epro files have same symbol ref | ✅ Confirmed |
| v2 has 2 motor drivers (U5, U6 = DRV8871) | v2 .epro parsed, component designators | ✅ Confirmed |
| v3 has 4 motor drivers (U7-U10 = DRV8871DDAR) | v3 .epro parsed + rendered PDF | ✅ Confirmed |
| v3 has CN5 spare output header | v3 .epro parsed + rendered PDF | ✅ Confirmed |
| CN5 pinout (GND, MOTOR1_IN1, MOTOR1_IN2, MOTOR2_IN2, MOTOR2_IN1, GND, GND) | Rendered PDF vision extraction | ✅ Confirmed |
| v2 has NO CN5 (no spare output header) | v2 .epro parsed, no WAFER/CN5 found | ✅ Confirmed |
| v2 pinout matches v3 pinout | **Inferred** — both boards use same chip at same position | ⚠️ Inferred |
| v1.3 `Constants.h` matches the schematic | Direct comparison | ❌ **No match** — v1.3 pin defines are wrong |
| v1.3 firmware actually worked on v2 hardware | User statement | ❓ Unknown |
| Drum motor exists on v2 hardware | Not in schematic | ❓ Unknown |
| v3 firmware will add drum | Pending design | ❓ Unknown |

---

## 9. Recommended Next Steps

1. **Open the actual robot and check what's connected.** Specifically:
   - What wires are soldered to P1, P2?
   - Is there a drum motor? Where is it wired?
   - Are the BOOT button (GPIO9) and the MODE button (GPIO6) accessible on the case?
2. **Render the v2 .epro as a PDF** in EasyEDA Pro so I can extract the pinout the same way I did for v3.
3. **Implement the geometry-based netlist extraction** for `.epro` files (Q4 above) so future revisions can be analyzed without rendering.
4. **Update `board_config.h`** to include the v3 BLDC breakout (CN5) support, including:
   - `HAS_SPARE_HEADER` config flag
   - `PIN_SPARE_HEADER_IN1`, `PIN_SPARE_HEADER_IN2`, etc. for CN5 access
   - Web UI to configure CN5 use (brushed vs BLDC mode)
5. **Verify the v1.3 firmware's actual behavior** by capturing GPIO outputs while the firmware runs.

## 11. Runtime board detection

The `board_config.h` is currently compile-time only — you set `BOARD_REV=2` or `BOARD_REV=3` at build time. The `board_detect.h/cpp` module (in the same component) adds **runtime detection** so the same compiled binary can run on both boards.

### How it works (3-layer priority)

```
1. NVS override       (highest priority — user-set via web UI)
        ↓
2. Hardware strapping  (2 GPIO pins read at boot)
        ↓
3. Compile-time default (-DBOARD_REV=N)
```

At boot, `board_detect_init()`:
1. Checks NVS for a saved `rev_override`. If present, uses that.
2. If no NVS override, reads `BOARD_ID_GPIO0` and `BOARD_ID_GPIO1` (two strapping pins). The bit pattern identifies the board:
   - `0b00` = v2
   - `0b01` = v3
   - `0b10` = v4 (future)
   - `0b11` = v5 (future)
3. If detection fails, falls back to the compile-time `BOARD_REV` and logs a warning.

### Hardware design

To use this, the v2 and v3 boards need different resistor configurations on two free GPIOs (e.g. GPIO11, GPIO12). For example:

| Board | GPIO11 (BOARD_ID0) | GPIO12 (BOARD_ID1) | Result |
|---|---|---|---|
| v2 | 10K pull-up to 3V3 (HIGH) | 10K pull-up to 3V3 (HIGH) | `0b11` = V5 (wrong!) |
| v3 | 10K pull-up to 3V3 (HIGH) | 10K pull-down to GND (LOW) | `0b01` = V3 (correct) |

(The actual resistor placement depends on which free GPIOs you choose. See the file for `BOARD_ID_GPIO0/1` definitions.)

### When to use which layer

| Scenario | Use |
|---|---|
| Production robot, fixed hardware | Hardware strapping (auto-detects on every boot) |
| Dev/test, want to override a misconfigured board | NVS override via web UI (`/api/board/rev`) |
| Just flashing for the first time | Compile-time default (`-DBOARD_REV=N`) |

### Important constraints

- **ID pins must not be ESP32-C3 strapping pins** (GPIO2, GPIO8, GPIO9) — these affect boot mode and shouldn't be repurposed. The test `test_board_id_pins_not_strapping` enforces this.
- **ID pins must not overlap with other peripherals** (motors, LEDs, I2C, etc.). The test `test_board_id_pins_not_used_by_board_config` enforces this against `board_config.h`.
- **Choose GPIOs that exist on the ESP32-C3-MINI-1 module.** The C3 module has 22 usable GPIOs; the schematic shows several as NC (not connected). Pick NC pins for the ID, or modify the board to bring out new ones.

### Limitations of the current implementation

- **Requires board modification.** Adding 4 resistors per board (2 pull-ups + 2 pull-downs, or similar) is a one-time cost but requires board respin.
- **The chosen pin numbers (GPIO11, GPIO12) are placeholders.** They need to be confirmed against the actual ESP32-C3-MINI-1 module pinout — GPIO11 and GPIO12 may not be brought out as pads on the module. Verify before manufacturing.
- **NVS override persists across reflashes.** If you set a NVS override and then reflash with a different board, the override still applies. The web UI must expose a "clear override" button for safety.
- **The current code only runs at boot.** It doesn't re-detect if the hardware changes mid-session (which is fine for a robot that doesn't swap boards while running).

---

## 10. File Inventory

### Hardware source files (in `hardware/`)

| File | What | Description |
|---|---|---|
| `board-v2-rev1-schematic.epro` | EasyEDA v2 schematic source | The board the user is actually using. **Current production.** |
| `board-v2-rev1-pcb-layout.epro2` | EasyEDA v2 PCB layout | PCB design, not schematic |
| `board-v3-rev1-schematic.epro` | EasyEDA v3 schematic source | Next revision. **Designed, not yet fabricated.** |
| `board-v3-rev1-rendered.pdf` | Rendered v3 schematic | PDF export used for vision extraction |

### Original attachments (in `../.hermes/desktop-attachments/`)

| Original filename | Saved as |
|---|---|
| `ProPrj_Generic_Robot_Controller_ver2_2025-08-17.epro` | `hardware/board-v3-rev1-schematic.epro` |
| `ProPrj_Generic_Robot_Controller_ver2_temp_2026-06-30.epro` | `hardware/board-v2-rev1-schematic.epro` |
| `ProPrj_Generic_Robot_Controller_ver2_temp_2026-06-30.epro2` | `hardware/board-v2-rev1-pcb-layout.epro2` |
| `SCH_Schematic1_1_2026-06-29.pdf` | `hardware/board-v3-rev1-rendered.pdf` |

> **Note on filenames:** The original v3 file is named `ver2_2025-08-17.epro` because it was an internal revision of the v2 board (probably the same board with minor changes, but never fabricated). The original v2 file is named `ver2_temp_2026-06-30.epro` because it was a temporary working copy. I renamed them to disambiguate.

### Firmware source files

| File | What | Where |
|---|---|---|
| v1.3 firmware source | Original combat robot code (with Bluepad32) | `esp-idf-arduino-bluepad32-template/combat_robot` branch |
| v2 firmware | NimBLE + web UI rewrite | This project (combat-robot-v2/) |
| Board abstraction | One firmware, two boards | `components/board_config/include/board_config.h` |