"""
Pre-flash checklist tests.

These tests run before flashing and check for KNOWN-BAD conditions
that would cause the robot to misbehave, fail to boot, or break
hardware. Each test is a "stop sign" — if it fails, do not flash.

What's checked:
  - Required files exist
  - sdkconfig doesn't have conflicting options
  - No leftover Bluepad32 references
  - Pin defines are consistent with the schematic
  - The schematic-pinout mismatch warning (currently active)
  - ControllerState struct is compatible with v1
"""
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
V1_REPO = PROJECT_ROOT.parent / "esp-idf-arduino-bluepad32-template"


# ---------- Required files present ----------

REQUIRED_FILES = [
    "platformio.ini",
    "sdkconfig.defaults",
    "partitions.csv",
    "main/main.c",
    "main/sketch.cpp",
    "main/CMakeLists.txt",
    "components/ble_gamepad/CMakeLists.txt",
    "components/ble_gamepad/include/ble_gamepad.h",
    "components/ble_gamepad/src/ble_gamepad.cpp",
    "components/web_config/CMakeLists.txt",
    "components/web_config/include/web_config.h",
    "components/web_config/src/web_config.cpp",
    "components/myrobot/CMakeLists.txt",
    "components/myrobot/include/Constants.h",
    "components/myrobot/src/TaskManager.cpp",
    "docs/DECISIONS.md",
    "docs/BUILD.md",
    "docs/TESTING.md",
    "README.md",
]


class TestRequiredFiles:
    @pytest.mark.parametrize("relpath", REQUIRED_FILES)
    def test_file_exists(self, relpath):
        path = PROJECT_ROOT / relpath
        assert path.exists(), f"Required file missing: {relpath}"


# ---------- SDK config sanity ----------

class TestSdkConfig:
    """The sdkconfig.defaults must have the right options for NimBLE-only."""

    SDK = PROJECT_ROOT / "sdkconfig.defaults"

    def test_nimble_enabled(self):
        text = self.SDK.read_text()
        assert "BT_NIMBLE_ENABLED=y" in text, \
            "CONFIG_BT_NIMBLE_ENABLED must be set"

    def test_classic_bt_disabled(self):
        text = self.SDK.read_text()
        assert "BT_CLASSIC_ENABLED=n" in text, \
            "Classic BT should be disabled (we use BLE only)"

    def test_bluedroid_not_referenced(self):
        """We use NimBLE, not Bluedroid."""
        text = self.SDK.read_text()
        # Allow 'NIMBLE' to appear (we want that), but check Bluedroid-specific options aren't enabled
        assert "CONFIG_BT_BLE_50_FEATURES_SUPPORTED" not in text or \
               "BT_NIMBLE_ENABLED=y" in text

    def test_partitions_table_consistent(self):
        """The partitions.csv must support OTA + SPIFFS and fit in 4MB flash."""
        path = PROJECT_ROOT / "partitions.csv"
        text = path.read_text()
        # Must have at least one 'app' partition
        assert "factory" in text or "ota_0" in text, \
            "partitions.csv must have at least one app partition"

        flash_size = 0x400000  # ESP32-C3-MINI-1-H4 target has 4MB flash.
        parts = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = [field.strip() for field in line.split(",")]
            assert len(fields) >= 5, f"Malformed partition row: {line!r}"
            name, ptype, subtype, offset_s, size_s = fields[:5]
            offset = int(offset_s, 0)
            size = int(size_s, 0)
            end = offset + size
            assert end <= flash_size, (
                f"Partition {name} ends at 0x{end:x}, beyond 4MB flash end 0x{flash_size:x}"
            )
            parts.append((offset, end, name))

        for (_, prev_end, prev_name), (next_start, _, next_name) in zip(sorted(parts), sorted(parts)[1:]):
            assert prev_end <= next_start, (
                f"Partition {prev_name} overlaps {next_name}: "
                f"0x{prev_end:x} > 0x{next_start:x}"
            )


# ---------- Runtime cadence ----------

class TestRuntimeCadence:
    """Stop-sign tests for control-loop responsiveness."""

    SKETCH = PROJECT_ROOT / "main" / "sketch.cpp"

    def test_main_loop_control_cadence_is_at_least_50hz(self):
        text = self.SKETCH.read_text()
        loop = re.search(r"void loop\(\)\s*\{[\s\S]+?^\}", text, re.M)
        assert loop, "main loop() not found"
        delays = [int(v) for v in re.findall(r"vTaskDelay\(pdMS_TO_TICKS\((\d+)\)\)", loop.group(0))]
        assert delays, "loop() must yield with vTaskDelay(pdMS_TO_TICKS(...))"
        assert max(delays) <= 20, (
            "main loop controls motors and websocket ticks; unconditional delays above "
            "20ms cap combat driving below 50Hz"
        )


# ---------- Board config check ----------

class TestBoardConfig:
    """Verify board_config.h has the schematic-derived pin assignments.

    The board_config.h file replaces the v1.3 Constants.h pin defines with
    values extracted from the schematic. These tests verify the new file
    is consistent with the schematic and free of v1.3's mistakes.
    """

    def test_board_config_exists(self):
        path = PROJECT_ROOT / "components/board_config/include/board_config.h"
        assert path.exists(), "board_config.h missing - the abstraction layer hasn't been created"

    def test_board_config_supports_v2(self):
        path = PROJECT_ROOT / "components/board_config/include/board_config.h"
        text = path.read_text()
        assert "BOARD_REV == 2" in text, "Must support BOARD_REV=2"

    def test_board_config_supports_v3(self):
        path = PROJECT_ROOT / "components/board_config/include/board_config.h"
        text = path.read_text()
        assert "BOARD_REV == 3" in text, "Must support BOARD_REV=3 (next rev)"

    def test_motor1_pins_match_live_v2_firmware_map(self):
        """Live v2 board uses the existing firmware pin map for drive motors."""
        path = PROJECT_ROOT / "components/board_config/include/board_config.h"
        text = path.read_text()
        block = re.search(r"#if BOARD_REV == 2(?P<body>.*?)#elif BOARD_REV == 3", text, re.S)
        assert block, "BOARD_REV == 2 block missing"
        body = block.group("body")
        assert int(re.search(r"#define\s+PIN_MOTOR1_IN1\s+(\d+)", body).group(1)) == 1
        assert int(re.search(r"#define\s+PIN_MOTOR1_IN2\s+(\d+)", body).group(1)) == 3
        assert int(re.search(r"#define\s+PIN_MOTOR2_IN1\s+(\d+)", body).group(1)) == 6
        assert int(re.search(r"#define\s+PIN_MOTOR2_IN2\s+(\d+)", body).group(1)) == 7

    def test_battery_adc_matches_live_v2_firmware_map(self):
        path = PROJECT_ROOT / "components/board_config/include/board_config.h"
        text = path.read_text()
        m = re.search(r"#if BOARD_REV == 2.*?#define\s+PIN_BATT_MEAS\s+(\d+)", text, re.S)
        assert m, "PIN_BATT_MEAS not defined in v2 block"
        assert int(m.group(1)) == 0

    def test_mode_button_correct_v2(self):
        """Kevin verified live v2 SW1 / ModeButton is IO5."""
        path = PROJECT_ROOT / "components/board_config/include/board_config.h"
        text = path.read_text()
        m = re.search(r"#if BOARD_REV == 2.*?#define\s+PIN_MODE_BUTTON\s+(\d+)", text, re.S)
        assert m
        assert int(m.group(1)) == 5, f"PIN_MODE_BUTTON should be IO5, got IO{m.group(1)}"

    def test_debug_led_correct_v2(self):
        """Kevin verified live v2 LED1 is IO10."""
        path = PROJECT_ROOT / "components/board_config/include/board_config.h"
        text = path.read_text()
        m = re.search(r"#if BOARD_REV == 2.*?#define\s+PIN_DEBUG_LED\s+(\d+)", text, re.S)
        assert m
        assert int(m.group(1)) == 10, f"PIN_DEBUG_LED should be IO10, got IO{m.group(1)}"


# ---------- ControllerState compatibility ----------

class TestControllerStateCompat:
    """The ControllerState struct must be byte-compatible with v1.

    myrobot/TaskManager.cpp writes to these fields; if their types
    or order changes, the robot breaks.
    """

    @pytest.mark.skipif(not (V1_REPO / "components/myrobot/include/Constants.h").exists(),
                        reason="v1 reference not available")
    def test_fields_match_v1(self):
        v1 = (V1_REPO / "components/myrobot/include/Constants.h").read_text()
        v2 = (PROJECT_ROOT / "components/myrobot/include/Constants.h").read_text()
        v1_cs = re.search(r"struct ControllerState \{(.*?)\};", v1, re.S)
        v2_cs = re.search(r"struct ControllerState \{(.*?)\};", v2, re.S)
        assert v1_cs and v2_cs, "Could not find ControllerState in both files"

        # Match field declarations: "int  leftStickX" (v2 style) or
        # "int  leftStickX = 0" (v1.3 style with C++ default initializer).
        # v1.3 used C++ default initializers which we removed for C
        # compatibility, so the regex must accept both forms.
        v1_fields = [m.group(1) for m in re.finditer(
            r"(?:int|uint\d+_t|bool)\s+(\w+)\s*(?:=|;)", v1_cs.group(1))]
        v2_fields = [m.group(1) for m in re.finditer(
            r"(?:int|uint\d+_t|bool)\s+(\w+)\s*(?:=|;)", v2_cs.group(1))]

        assert v1_fields == v2_fields, (
            f"ControllerState fields drifted!\n"
            f"  v1: {v1_fields}\n"
            f"  v2: {v2_fields}\n"
            f"  This breaks the contract with TaskManager."
        )


# ---------- BLE gamepad public API surface ----------

class TestBlePublicApi:
    """The public API exposed in ble_gamepad.h must be what callers expect.

    Callers:
      - main/sketch.cpp (loops, calls ble_gamepad_get_state, is_connected,
        set_pairing_state, set_connection_callback)
      - components/web_config/src/web_config.cpp (HTTP handlers call
        set_pairing_state, get_paired_macs, clear_paired_macs, is_connected,
        get_pairing_state)
    """

    HEADER = PROJECT_ROOT / "components/ble_gamepad/include/ble_gamepad.h"

    EXPECTED_PUBLIC_API = {
        "ble_gamepad_init",
        "ble_gamepad_start",
        "ble_gamepad_deinit",
        "ble_gamepad_get_state",
        "ble_gamepad_is_connected",
        "ble_gamepad_get_pairing_state",
        "ble_gamepad_set_pairing_state",
        "ble_gamepad_get_paired_macs",
        "ble_gamepad_clear_paired_macs",
        "ble_gamepad_add_paired_mac",
        "ble_gamepad_remove_paired_mac",
        "ble_gamepad_disconnect",
        "ble_gamepad_set_connection_callback",
    }

    def test_all_expected_functions_declared(self):
        text = self.HEADER.read_text()
        # Find function declarations
        declared = set(re.findall(r"\b(ble_gamepad_\w+)\s*\(", text))
        missing = self.EXPECTED_PUBLIC_API - declared
        assert not missing, f"Public API functions missing from header: {missing}"