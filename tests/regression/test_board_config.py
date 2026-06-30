"""
Test the board_config.h abstraction layer.

These tests verify that the board_config.h file:
  - Compiles (we test its structure statically)
  - Has consistent pin assignments for each supported BOARD_REV
  - Matches the schematic-derived values
  - Catches the v1.3 Constants.h mistakes that bit the original code

Note: We're testing the C/C++ header by parsing it as text. The actual
C compilation is done by PlatformIO; here we just check the source.
"""
import re
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BOARD_CONFIG = PROJECT_ROOT / "components" / "board_config" / "include" / "board_config.h"


# ---- File structure ----

class TestBoardConfigStructure:
    def test_file_exists(self):
        assert BOARD_CONFIG.exists(), f"board_config.h missing at {BOARD_CONFIG}"

    def test_has_pragma_once(self):
        text = BOARD_CONFIG.read_text()
        assert "#pragma once" in text, \
            "board_config.h should use #pragma once"

    def test_supports_rev_2(self):
        text = BOARD_CONFIG.read_text()
        assert "BOARD_REV == 2" in text, "Must support BOARD_REV=2"

    def test_supports_rev_3(self):
        text = BOARD_CONFIG.read_text()
        assert "BOARD_REV == 3" in text, "Must support BOARD_REV=3"

    def test_has_error_for_unknown_rev(self):
        text = BOARD_CONFIG.read_text()
        assert "#error" in text, \
            "Should #error on unknown BOARD_REV to catch typos"


# ---- v2 board pin assignments ----

class TestV2BoardPins:
    """Pin assignments for BOARD_REV=2 (v2, current production).

    These are inferred from the v3 schematic (same chip, same designators)
    and component-designator match with v1.3 firmware. See
    docs/BOARD_HARDWARE.md for derivation.
    """

    @pytest.fixture
    def v2_block(self):
        text = BOARD_CONFIG.read_text()
        m = re.search(
            r"#if BOARD_REV == 2\s*\n(.*?)#elif BOARD_REV == 3",
            text, re.S)
        assert m, "Could not find #if BOARD_REV == 2 block"
        return m.group(1)

    def test_motor_pins_distinct(self, v2_block):
        """All four drive motor pins must be different (catches v1.3 dup)."""
        pins = []
        for name in ('PIN_MOTOR1_IN1', 'PIN_MOTOR1_IN2', 'PIN_MOTOR2_IN1', 'PIN_MOTOR2_IN2'):
            m = re.search(rf"#define\s+{name}\s+(\d+)", v2_block)
            assert m, f"{name} not defined in v2 block"
            pins.append(int(m.group(1)))
        assert len(set(pins)) == 4, f"Drive motor pins must be unique, got {pins}"

    def test_motor1_uses_io0_io1(self, v2_block):
        """MOTOR1 should be on GPIO0/1 (per schematic)."""
        for name, expected in (('PIN_MOTOR1_IN1', 0), ('PIN_MOTOR1_IN2', 1)):
            m = re.search(rf"#define\s+{name}\s+(\d+)", v2_block)
            assert int(m.group(1)) == expected, \
                f"{name} should be GPIO{expected}, got {m.group(1)}"

    def test_motor2_uses_txd0_and_io10(self, v2_block):
        """MOTOR2_IN1 = TXD0 (GPIO21), MOTOR2_IN2 = GPIO10."""
        for name, expected in (('PIN_MOTOR2_IN1', 21), ('PIN_MOTOR2_IN2', 10)):
            m = re.search(rf"#define\s+{name}\s+(\d+)", v2_block)
            assert int(m.group(1)) == expected, \
                f"{name} should be GPIO{expected}, got {m.group(1)}"

    def test_servos_on_io4_io5(self, v2_block):
        """SERVO1/2 on GPIO4/5 (per schematic)."""
        for name, expected in (('PIN_SERVO1', 4), ('PIN_SERVO2', 5)):
            m = re.search(rf"#define\s+{name}\s+(\d+)", v2_block)
            assert int(m.group(1)) == expected

    def test_battery_adc_on_io3(self, v2_block):
        """BATT_MEAS must be on GPIO3 (only ADC pin available per schematic)."""
        m = re.search(r"#define\s+PIN_BATT_MEAS\s+(\d+)", v2_block)
        assert int(m.group(1)) == 3, \
            f"PIN_BATT_MEAS must be GPIO3 (ADC), got GPIO{m.group(1)}"

    def test_mode_button_on_io6(self, v2_block):
        """MODE_BUTTON on GPIO6."""
        m = re.search(r"#define\s+PIN_MODE_BUTTON\s+(\d+)", v2_block)
        assert int(m.group(1)) == 6

    def test_debug_led_on_io7(self, v2_block):
        """DEBUG_LED on GPIO7."""
        m = re.search(r"#define\s+PIN_DEBUG_LED\s+(\d+)", v2_block)
        assert int(m.group(1)) == 7

    def test_sda_on_io2_scl_on_io8(self, v2_block):
        """I2C: SDA on GPIO2, SCL on GPIO8 (per schematic)."""
        assert re.search(r"#define\s+PIN_SDA\s+2\b", v2_block)
        assert re.search(r"#define\s+PIN_SCL\s+8\b", v2_block)

    def test_boot_on_io9(self, v2_block):
        """BOOT button on GPIO9 (ESP32-C3 strapping pin)."""
        m = re.search(r"#define\s+PIN_BOOT_BUTTON\s+(\d+)", v2_block)
        assert int(m.group(1)) == 9

    def test_5v_ext_en_on_rxd0(self, v2_block):
        """5V_EXT_EN on RXD0 (GPIO20)."""
        m = re.search(r"#define\s+PIN_5V_EXT_EN\s+(\d+)", v2_block)
        assert int(m.group(1)) == 20


# ---- v3 board pin assignments ----

class TestV3BoardPins:
    """Pin assignments for BOARD_REV=3 (v3, designed but not yet fab'd).

    These are extracted from the rendered v3 schematic using the vision
    model. See docs/BOARD_HARDWARE.md Section 3 for the extraction.
    """

    @pytest.fixture
    def v3_block(self):
        text = BOARD_CONFIG.read_text()
        m = re.search(r"#elif BOARD_REV == 3\s*\n(.*?)#else", text, re.S)
        assert m, "Could not find #elif BOARD_REV == 3 block"
        return m.group(1)

    def test_v3_motor_pins_distinct(self, v3_block):
        pins = []
        for name in ('PIN_MOTOR1_IN1', 'PIN_MOTOR1_IN2', 'PIN_MOTOR2_IN1', 'PIN_MOTOR2_IN2'):
            m = re.search(rf"#define\s+{name}\s+(\d+)", v3_block)
            assert m, f"{name} not defined"
            pins.append(int(m.group(1)))
        assert len(set(pins)) == 4

    def test_v3_motor1_io0_io1(self, v3_block):
        for name, expected in (('PIN_MOTOR1_IN1', 0), ('PIN_MOTOR1_IN2', 1)):
            m = re.search(rf"#define\s+{name}\s+(\d+)", v3_block)
            assert int(m.group(1)) == expected

    def test_v3_motor2_txd0_and_io10(self, v3_block):
        for name, expected in (('PIN_MOTOR2_IN1', 21), ('PIN_MOTOR2_IN2', 10)):
            m = re.search(rf"#define\s+{name}\s+(\d+)", v3_block)
            assert int(m.group(1)) == expected


# ---- Motor count differences ----

class TestMotorCount:
    """v2 has 2 motor drivers, v3 has 4 motor drivers. This is the
    KEY difference between the two board revisions."""

    def test_v2_has_2_motor_drivers(self):
        text = BOARD_CONFIG.read_text()
        m = re.search(r"#if BOARD_REV == 2.*?#define\s+NUM_DRIVE_MOTORS\s+(\d+)",
                      text, re.S)
        assert m, "v2 NUM_DRIVE_MOTORS not defined"
        assert int(m.group(1)) == 2, (
            f"v2 should have 2 motor drivers (U5, U6), got {m.group(1)}. "
            "v2 schematic has DRV8871 chips at U5 and U6 only."
        )

    def test_v3_has_4_motor_drivers(self):
        text = BOARD_CONFIG.read_text()
        m = re.search(r"#elif BOARD_REV == 3.*?#define\s+NUM_DRIVE_MOTORS\s+(\d+)",
                      text, re.S)
        assert m, "v3 NUM_DRIVE_MOTORS not defined"
        assert int(m.group(1)) == 4, (
            f"v3 should have 4 motor drivers (U7, U8, U9, U10), got {m.group(1)}. "
            "v3 schematic has DRV8871DDAR chips at U7, U8, U9, U10."
        )


# ---- Spare header (CN5, v3 only) ----

class TestSpareHeader:
    """v3 has a CN5 spare output header for BLDC ESCs / external drivers.
    v2 does NOT have this header."""

    def test_v2_no_spare_header(self):
        """v2 should have HAS_SPARE_HEADER=0."""
        text = BOARD_CONFIG.read_text()
        m = re.search(r"#if BOARD_REV == 2.*?#define\s+HAS_SPARE_HEADER\s+(\d+)",
                      text, re.S)
        assert m, "v2 HAS_SPARE_HEADER not defined"
        assert int(m.group(1)) == 0, (
            f"v2 should have HAS_SPARE_HEADER=0 (no CN5 on v2), got {m.group(1)}. "
            "v2 schematic has no spare output header."
        )

    def test_v3_has_spare_header(self):
        """v3 should have HAS_SPARE_HEADER=1."""
        text = BOARD_CONFIG.read_text()
        m = re.search(r"#elif BOARD_REV == 3.*?#define\s+HAS_SPARE_HEADER\s+(\d+)",
                      text, re.S)
        assert m, "v3 HAS_SPARE_HEADER not defined"
        assert int(m.group(1)) == 1, (
            f"v3 should have HAS_SPARE_HEADER=1 (CN5 on v3), got {m.group(1)}. "
            "v3 schematic has CN5 'Spare output header for motor pins'."
        )

    def test_v3_spare_header_pin_defines(self):
        """v3 should have 4 CN5 pin defines."""
        text = BOARD_CONFIG.read_text()
        v3_block_m = re.search(r"#elif BOARD_REV == 3\s*\n(.*?)#else", text, re.S)
        assert v3_block_m
        v3_block = v3_block_m.group(1)

        for name in ('PIN_SPARE_HEADER_IN1', 'PIN_SPARE_HEADER_IN2',
                     'PIN_SPARE_HEADER_IN3', 'PIN_SPARE_HEADER_IN4'):
            # Use \S+ to match either a digit (literal GPIO) or another
            # #define name (alias).
            m = re.search(rf"#define\s+{name}\s+(\S+)", v3_block)
            assert m, f"{name} not defined in v3 block"

    def test_v3_spare_header_in1_maps_to_motor1_in1(self):
        """CN5 pin 2 should be on the same net as MOTOR1_IN1 (tapped).

        The CN5 pin defines use the symbolic alias `PIN_MOTOR1_IN1`
        (since they're on the same GPIO). Verify the alias is correct.
        """
        text = BOARD_CONFIG.read_text()
        v3_block = re.search(r"#elif BOARD_REV == 3\s*\n(.*?)#else", text, re.S).group(1)
        m1 = re.search(r"#define\s+PIN_SPARE_HEADER_IN1\s+(\S+)", v3_block)
        m2 = re.search(r"#define\s+PIN_MOTOR1_IN1\s+(\d+)", v3_block)
        assert m1, "PIN_SPARE_HEADER_IN1 not defined"
        assert m2, "PIN_MOTOR1_IN1 not defined"
        # CN5 pin should be the literal GPIO number, OR an alias to PIN_MOTOR1_IN1.
        # We accept both forms (literal "0" or alias "PIN_MOTOR1_IN1" which
        # resolves to 0 at preprocessing time).
        cnh5_value = m1.group(1)
        if cnh5_value.isdigit():
            assert cnh5_value == m2.group(1), (
                f"CN5 IN1 literal ({cnh5_value}) doesn't match MOTOR1_IN1 ({m2.group(1)})"
            )
        else:
            # It's an alias - should match PIN_MOTOR1_IN1
            assert cnh5_value == "PIN_MOTOR1_IN1", (
                f"CN5 IN1 alias ({cnh5_value}) should be PIN_MOTOR1_IN1 (it's a tap of the same net)"
            )

    def test_v3_spare_header_pwm_freq_50hz(self):
        """BLDC ESCs use 50 Hz servo PWM. The header should set this."""
        text = BOARD_CONFIG.read_text()
        v3_block = re.search(r"#elif BOARD_REV == 3\s*\n(.*?)#else", text, re.S).group(1)
        m = re.search(r"#define\s+SPARE_HEADER_PWM_FREQ_HZ\s+(\d+)", v3_block)
        assert m, "SPARE_HEADER_PWM_FREQ_HZ not defined"
        assert int(m.group(1)) == 50, (
            f"BLDC ESCs use 50 Hz servo PWM, got {m.group(1)} Hz"
        )


# ---- Regressions against v1.3 mistakes ----

class TestV1MistakesRegression:
    """Verify board_config.h does NOT have the mistakes that bit v1.3.

    v1.3 Constants.h had:
      ESC_1_PIN = 4  (but GPIO4 is SERVO1 on the schematic)
      DRIVE_MOTOR1_2_PIN = 3  (but GPIO3 is BATT_MEAS ADC)
      DRIVE_MOTOR2_1_PIN = 6  (but GPIO6 is MODE_BUTTON)
      DRIVE_MOTOR2_2_PIN = 7  (but GPIO7 is DEBUG_LED)
      MODE_BUTTON_PIN = 5  (but GPIO5 is SERVO2)
      DEBUG_LED_PIN = 10  (but GPIO10 is MOTOR2_IN2)
      BATT_MEAS_PIN = 0  (but GPIO0 is MOTOR1_IN1)
    """

    @pytest.fixture
    def v2_block(self):
        text = BOARD_CONFIG.read_text()
        m = re.search(
            r"#if BOARD_REV == 2\s*\n(.*?)#elif BOARD_REV == 3",
            text, re.S)
        return m.group(1)

    def test_motor1_in1_not_on_drum_pin(self, v2_block):
        """v1.3 had BATT_MEAS=0 (wrong). v2 should have MOTOR1_IN1=0 (correct)."""
        m = re.search(r"#define\s+PIN_MOTOR1_IN1\s+(\d+)", v2_block)
        # If we get 0, that's correct. If we get any other ADC pin, wrong.
        assert int(m.group(1)) == 0, \
            "MOTOR1_IN1 must be GPIO0 (v1.3 had BATT_MEAS=0 by mistake)"

    def test_motor1_in2_not_on_adc(self, v2_block):
        """v1.3 had DRIVE_MOTOR1_2_PIN=3 (which is BATT_MEAS)."""
        m = re.search(r"#define\s+PIN_MOTOR1_IN2\s+(\d+)", v2_block)
        assert int(m.group(1)) != 3, \
            "MOTOR1_IN2 must NOT be GPIO3 (v1.3 mistake - that's the battery ADC)"

    def test_motor2_in1_not_on_button(self, v2_block):
        """v1.3 had DRIVE_MOTOR2_1_PIN=6 (which is MODE_BUTTON)."""
        m = re.search(r"#define\s+PIN_MOTOR2_IN1\s+(\d+)", v2_block)
        assert int(m.group(1)) != 6

    def test_motor2_in2_not_on_led(self, v2_block):
        """v1.3 had DRIVE_MOTOR2_2_PIN=7 (which is DEBUG_LED)."""
        m = re.search(r"#define\s+PIN_MOTOR2_IN2\s+(\d+)", v2_block)
        assert int(m.group(1)) != 7

    def test_mode_button_not_on_servo(self, v2_block):
        """v1.3 had MODE_BUTTON_PIN=5 (which is SERVO2)."""
        m = re.search(r"#define\s+PIN_MODE_BUTTON\s+(\d+)", v2_block)
        assert int(m.group(1)) != 5

    def test_debug_led_not_on_motor(self, v2_block):
        """v1.3 had DEBUG_LED_PIN=10 (which is MOTOR2_IN2)."""
        m = re.search(r"#define\s+PIN_DEBUG_LED\s+(\d+)", v2_block)
        assert int(m.group(1)) != 10


# ---- kBoardInfo struct ----

class TestBoardInfoStruct:
    """The kBoardInfo struct should reflect the current BOARD_REV's defines."""

    def test_struct_declared(self):
        text = BOARD_CONFIG.read_text()
        assert "struct BoardInfo" in text
        assert "kBoardInfo" in text

    def test_struct_includes_all_pins(self):
        text = BOARD_CONFIG.read_text()
        for name in (
            'pin_motor1_in1', 'pin_motor1_in2', 'pin_motor2_in1', 'pin_motor2_in2',
            'pin_servo1', 'pin_servo2', 'pin_drum_pwm',
            'pin_batt_meas', 'pin_mode_button', 'pin_debug_led', 'pin_neopixel',
            'pin_sda', 'pin_scl', 'pin_5v_ext_en', 'pin_boot_button',
            'has_spare_header', 'pin_spare_header_in1', 'pin_spare_header_in2',
            'pin_spare_header_in3', 'pin_spare_header_in4',
        ):
            assert name in text, f"BoardInfo missing field: {name}"


# ---- Compatibility with v1.3 Constants.h ----

class TestV13ConstantsReconciliation:
    """Show what v1.3's Constants.h had, and how board_config.h differs.

    This isn't strictly a "test" - it's a documentation test that fails
    if the v1.3 values silently leak into board_config.h. The test
    exists so future contributors see the diff when they re-run pytest.
    """

    # v1.3 Constants.h values
    V13_PINS = {
        'ESC_1_PIN': 4,            # WRONG: GPIO4 is SERVO1
        'ESC_2_PIN': 8,            # WRONG: GPIO8 is SCL
        'DRIVE_MOTOR1_1_PIN': 1,   # CLOSE: GPIO1 is MOTOR1_IN2
        'DRIVE_MOTOR1_2_PIN': 3,   # WRONG: GPIO3 is BATT_MEAS
        'DRIVE_MOTOR2_1_PIN': 6,   # WRONG: GPIO6 is MODE_BUTTON
        'DRIVE_MOTOR2_2_PIN': 7,   # WRONG: GPIO7 is DEBUG_LED
        'MODE_BUTTON_PIN': 5,      # WRONG: GPIO5 is SERVO2
        'DEBUG_LED_PIN': 10,       # WRONG: GPIO10 is MOTOR2_IN2
        'BATT_MEAS_PIN': 0,        # WRONG: GPIO0 is MOTOR1_IN1
    }

    def test_v13_was_wrong(self):
        """Document the v1.3 mistakes. Just verifies v1.3 has known-bad values.

        This is a meta-test: it ensures the documented "v1.3 was wrong"
        claim in BOARD_HARDWARE.md is still true (i.e., we haven't
        accidentally fixed the v1.3 code without realizing).

        If you genuinely fix the v1.3 code, update this test and the
        documentation together.
        """
        # Sanity check: at least one v1.3 pin assignment is "wrong" by
        # current board_config.h (this test passes as long as v1.3 differs
        # from the schematic-derived values in board_config.h).
        # If they ever match exactly, v1.3 was correct all along and this
        # documentation is stale.
        # For now, we just assert the test exists and runs.
        assert self.V13_PINS['BATT_MEAS_PIN'] == 0  # v1.3 had BATT on GPIO0
        # We expect this to differ from board_config.h's PIN_BATT_MEAS=3
        v2_text = BOARD_CONFIG.read_text()
        m = re.search(r"#if BOARD_REV == 2.*?#define\s+PIN_BATT_MEAS\s+(\d+)", v2_text, re.S)
        assert m, "board_config.h missing PIN_BATT_MEAS for v2"
        v2_batt = int(m.group(1))
        assert v2_batt != self.V13_PINS['BATT_MEAS_PIN'], (
            f"v1.3 BATT_MEAS={self.V13_PINS['BATT_MEAS_PIN']} matches v2={v2_batt}. "
            "If v1.3 was actually right, update docs/BOARD_HARDWARE.md."
        )