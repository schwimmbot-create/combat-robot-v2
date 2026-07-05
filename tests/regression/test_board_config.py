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

    These are the live v2 firmware/harness pins. Kevin verified LED1 is IO10
    and SW1 / ModeButton is IO5; earlier GPIO6/GPIO7 assumptions were from a
    stale schematic interpretation and broke the physical board.
    """

    @pytest.fixture
    def v2_block(self):
        text = BOARD_CONFIG.read_text()
        m = re.search(
            r"#if BOARD_REV == 2\s*\n(.*?)#elif BOARD_REV == 3",
            text, re.S)
        assert m, "Could not find #if BOARD_REV == 2 block"
        return m.group(1)

    def _pin(self, v2_block, name):
        m = re.search(rf"#define\s+{name}\s+(\d+)", v2_block)
        assert m, f"{name} not defined in v2 block"
        return int(m.group(1))

    def test_motor_pins_distinct(self, v2_block):
        pins = [self._pin(v2_block, name) for name in (
            'PIN_MOTOR1_IN1', 'PIN_MOTOR1_IN2', 'PIN_MOTOR2_IN1', 'PIN_MOTOR2_IN2')]
        assert len(set(pins)) == 4, f"Drive motor pins must be unique, got {pins}"

    def test_motor1_uses_live_v2_io1_io3(self, v2_block):
        assert self._pin(v2_block, 'PIN_MOTOR1_IN1') == 1
        assert self._pin(v2_block, 'PIN_MOTOR1_IN2') == 3

    def test_motor2_uses_live_v2_io6_io7(self, v2_block):
        assert self._pin(v2_block, 'PIN_MOTOR2_IN1') == 6
        assert self._pin(v2_block, 'PIN_MOTOR2_IN2') == 7

    def test_aux_outputs_on_io4_io8(self, v2_block):
        assert self._pin(v2_block, 'PIN_SERVO1') == 4
        assert self._pin(v2_block, 'PIN_SERVO2') == 8

    def test_battery_adc_on_io0(self, v2_block):
        assert self._pin(v2_block, 'PIN_BATT_MEAS') == 0

    def test_mode_button_on_io5(self, v2_block):
        assert self._pin(v2_block, 'PIN_MODE_BUTTON') == 5

    def test_debug_led_on_io10(self, v2_block):
        assert self._pin(v2_block, 'PIN_DEBUG_LED') == 10

    def test_sda_on_io2_scl_on_io8(self, v2_block):
        assert re.search(r"#define\s+PIN_SDA\s+2\b", v2_block)
        assert re.search(r"#define\s+PIN_SCL\s+8\b", v2_block)

    def test_boot_on_io9(self, v2_block):
        assert self._pin(v2_block, 'PIN_BOOT_BUTTON') == 9

    def test_5v_ext_en_on_rxd0(self, v2_block):
        assert self._pin(v2_block, 'PIN_5V_EXT_EN') == 20


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

class TestLiveV2MapRegression:
    """Guard against reintroducing the stale GPIO6/GPIO7 interpretation.

    The previous board_config draft moved SW1 to IO6 and LED1 to IO7. Kevin
    verified the live v2 board uses SW1 / ModeButton on IO5 and LED1 on IO10.
    """

    @pytest.fixture
    def v2_block(self):
        text = BOARD_CONFIG.read_text()
        m = re.search(
            r"#if BOARD_REV == 2\s*\n(.*?)#elif BOARD_REV == 3",
            text, re.S)
        return m.group(1)

    def _pin(self, v2_block, name):
        m = re.search(rf"#define\s+{name}\s+(\d+)", v2_block)
        assert m, f"{name} not defined"
        return int(m.group(1))

    def test_mode_button_not_on_stale_io6(self, v2_block):
        assert self._pin(v2_block, 'PIN_MODE_BUTTON') == 5
        assert self._pin(v2_block, 'PIN_MODE_BUTTON') != 6

    def test_debug_led_not_on_stale_io7(self, v2_block):
        assert self._pin(v2_block, 'PIN_DEBUG_LED') == 10
        assert self._pin(v2_block, 'PIN_DEBUG_LED') != 7

    def test_led1_does_not_collide_with_motor2_in2(self, v2_block):
        assert self._pin(v2_block, 'PIN_DEBUG_LED') != self._pin(v2_block, 'PIN_MOTOR2_IN2')

    def test_sw1_does_not_collide_with_motor2_in1(self, v2_block):
        assert self._pin(v2_block, 'PIN_MODE_BUTTON') != self._pin(v2_block, 'PIN_MOTOR2_IN1')


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
    """Document that the live v2 firmware map intentionally matches the
    legacy Constants.h aliases for the pins Kevin verified on hardware.
    """

    V13_PINS = {
        'ESC_1_PIN': 4,
        'ESC_2_PIN': 8,
        'DRIVE_MOTOR1_1_PIN': 1,
        'DRIVE_MOTOR1_2_PIN': 3,
        'DRIVE_MOTOR2_1_PIN': 6,
        'DRIVE_MOTOR2_2_PIN': 7,
        'MODE_BUTTON_PIN': 5,
        'DEBUG_LED_PIN': 10,
        'BATT_MEAS_PIN': 0,
    }

    def test_live_v2_preserves_verified_legacy_sw1_and_led_pins(self):
        v2_text = BOARD_CONFIG.read_text()
        mode = re.search(r"#if BOARD_REV == 2.*?#define\s+PIN_MODE_BUTTON\s+(\d+)", v2_text, re.S)
        led = re.search(r"#if BOARD_REV == 2.*?#define\s+PIN_DEBUG_LED\s+(\d+)", v2_text, re.S)
        assert mode and led
        assert int(mode.group(1)) == self.V13_PINS['MODE_BUTTON_PIN'] == 5
        assert int(led.group(1)) == self.V13_PINS['DEBUG_LED_PIN'] == 10
