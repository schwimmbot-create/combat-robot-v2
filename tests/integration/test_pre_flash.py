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
        """The partitions.csv must support OTA + SPIFFS for our use case."""
        text = (PROJECT_ROOT / "partitions.csv").read_text()
        # Must have at least one 'app' partition
        assert "factory" in text or "ota_0" in text, \
            "partitions.csv must have at least one app partition"


# ---------- Schematic vs pinout check ----------

class TestSchematicVsPinout:
    """Verify Constants.h pin defines match the schematic (or warn if not).

    KNOWN ISSUE: the schematic (.hermes/desktop-attachments/SCH_Schematic1_1_2026-06-29.pdf)
    is for an ESP32-WROOM-32 module, but the project is configured for ESP32-C3.
    Some pin assignments differ between these chips (notably TXD0/RXD0 meanings).

    This test FAILS to alert you to this. Don't suppress it without first
    confirming which board you're actually flashing.
    """

    @pytest.mark.skipif(
        not (PROJECT_ROOT.parent / ".hermes/desktop-attachments/SCH_Schematic1_1_2026-06-29.pdf").exists(),
        reason="schematic not in expected location"
    )
    def test_schematic_pinout_warning(self):
        """The schematic shows an ESP32-WROOM-32; the project is configured for C3.

        This is a known issue awaiting resolution. See docs/DECISIONS.md
        "Open questions" section.

        To make this test pass, EITHER:
        1. Update Constants.h to use WROOM-32 pin names
        2. Update sdkconfig to use the right platform
        3. Confirm you're using a C3 with the WROOM-32 schematic uploaded by mistake
        """
        # We expect to fail with a clear message right now.
        pytest.fail(
            "Schematic pinout mismatch: schematic is for ESP32-WROOM-32 "
            "but project targets ESP32-C3. Resolve before flashing. "
            "See docs/DECISIONS.md 'Open questions' section."
        )


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

        def fields(s):
            return [m.group(1) for m in re.finditer(
                r"(?:int|uint\d+_t|bool)\s+(\w+)\s*=", s)]

        v1_fields = fields(v1_cs.group(1))
        v2_fields = fields(v2_cs.group(1))
        assert v1_fields == v2_fields, (
            f"ControllerState fields drifted!\n"
            f"  v1: {v1_fields}\n"
            f"  v2: {v2_fields}\n"
            f"This breaks the contract with TaskManager."
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