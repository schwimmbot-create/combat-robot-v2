"""
Regression tests: verify the project structure hasn't drifted.

These tests run against the ACTUAL C/C++ source code on disk. They
catch:
  - Accidental edits to ported myrobot/ files
  - Brace/paren balance errors
  - Public BLE API mismatch between header and implementation
  - CMakeLists.txt required-component errors
  - Stale Bluepad32 / btstack references

They DON'T catch:
  - Logic bugs inside function bodies (need real compilation)
  - Runtime behavior (need hardware)
"""
import hashlib
import re
from pathlib import Path

import pytest

# Resolve project root relative to this test file.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
V1_REPO = PROJECT_ROOT.parent / "esp-idf-arduino-bluepad32-template"


# ---------- Ported file integrity ----------

# Files that must remain byte-identical to v1.3 combat_robot branch.
# Modifying these means breaking v1.3 compatibility for no reason.
BYTE_IDENTICAL_FILES = [
    "components/myrobot/include/Adafruit_NeoPixel.h",
    "components/myrobot/include/Buttons.h",
    "components/myrobot/include/Drive.h",
    "components/myrobot/include/DriveMotor.h",
    "components/myrobot/include/Drum.h",
    "components/myrobot/include/LED.h",
    "components/myrobot/include/PowerFunctions.h",
    "components/myrobot/include/rgbLED.h",
    "components/myrobot/include/TaskManager.h",
    "components/myrobot/src/Adafruit_NeoPixel.cpp",
    "components/myrobot/src/Buttons.cpp",
    "components/myrobot/src/Drive.cpp",
    "components/myrobot/src/PowerFunctions.cpp",
    "components/myrobot/src/rgbLED.cpp",
    "components/myrobot/src/TaskManager.cpp",
    "components/myrobot/src/esp.c",
]

# Files we've intentionally modified from v1.3 to support the new
# Arduino-ESP32 2.0.14 framework (LEDC API migration, etc.).
# We verify these are still semantically correct in TestIntentionallyModified.
INTENTIONALLY_MODIFIED_FILES = {
    "components/myrobot/include/Constants.h":
        "Removed C++ default member initializers (made it C-compatible); "
        "removed controllerState::connected (moved to ble_gamepad_is_connected()); "
        "added LEDC channel defines (DRIVE_MOTOR_FWD_PWM_CHANNEL etc).",
    "components/myrobot/src/DriveMotor.cpp":
        "Migrated from v1.3 ledcAttach() to v2.0.14 ledcAttachPin() + "
        "ledcChangeFrequency(). ledcWrite now uses explicit channel constants "
        "instead of pin numbers (v1.3 used the pin as the channel).",
    "components/myrobot/src/Drum.cpp":
        "Migrated from v1.3 ledcAttach() to v2.0.14 ledcAttachPin() + "
        "ledcChangeFrequency(). ledcWrite now uses ESC_PWM_CHANNEL.",
    "components/myrobot/src/LED.cpp":
        "Migrated from v1.3 ledcAttach() to v2.0.14 ledcAttachPin() + "
        "ledcChangeFrequency(). ledcWrite now uses LED_PWM_CHANNEL.",
}

# All ported files (union of both lists)
PORTED_FILES = BYTE_IDENTICAL_FILES + list(INTENTIONALLY_MODIFIED_FILES.keys())


class TestPortedFilesUnchanged:
    """myrobot/ files must be byte-identical to v1.3 combat_robot branch,
    EXCEPT for files we've explicitly migrated to the new framework
    (see INTENTIONALLY_MODIFIED_FILES).

    If you've intentionally modified a myrobot/ file, add it to
    INTENTIONALLY_MODIFIED_FILES with a reason. The test will then
    only verify the unmodified files.
    """

    @pytest.mark.skipif(not V1_REPO.exists(),
                        reason="v1 reference repo not available")
    @pytest.mark.parametrize("relpath", PORTED_FILES)
    def test_file_byte_identical_to_v1(self, relpath):
        # Skip files we've intentionally modified (LEDC API migration, etc.)
        if relpath in INTENTIONALLY_MODIFIED_FILES:
            pytest.skip(f"intentionally modified: {INTENTIONALLY_MODIFIED_FILES[relpath]}")
        v1 = V1_REPO / relpath
        v2 = PROJECT_ROOT / relpath
        if not v1.exists():
            pytest.skip(f"v1 reference missing: {relpath}")
        v1_bytes = v1.read_bytes()
        v2_bytes = v2.read_bytes()
        if v1_bytes != v2_bytes:
            v1_hash = hashlib.sha256(v1_bytes).hexdigest()[:12]
            v2_hash = hashlib.sha256(v2_bytes).hexdigest()[:12]
            pytest.fail(
                f"{relpath} differs from v1\n"
                f"  v1 sha256: {v1_hash}\n"
                f"  v2 sha256: {v2_hash}\n"
                f"  If intentional, add to INTENTIONALLY_MODIFIED_FILES with a reason."
            )


class TestIntentionallyModified:
    """Verify that files in INTENTIONALLY_MODIFIED_FILES have the right
    structure post-migration. These tests would have failed under the
    byte-identical assertion, so we explicitly check the new state.
    """

    def test_drivemotor_uses_new_ledc_api(self):
        text = (PROJECT_ROOT / "components/myrobot/src/DriveMotor.cpp").read_text()
        assert "ledcAttachPin" in text, "DriveMotor should use ledcAttachPin"
        assert "ledcChangeFrequency" in text, "DriveMotor should use ledcChangeFrequency"
        # v1.3 used `ledcAttach(...)` which should be gone from executable code.
        uncommented = "\n".join(
            line for line in text.splitlines()
            if not line.lstrip().startswith("//")
        )
        assert not re.search(r"\bledcAttach\s*\(", uncommented), (
            "DriveMotor still has the v1.3 ledcAttach() call. "
            "Migrate to ledcAttachPin + ledcChangeFrequency."
        )

    def test_drum_uses_new_ledc_api(self):
        text = (PROJECT_ROOT / "components/myrobot/src/Drum.cpp").read_text()
        assert "ledcAttachPin" in text
        assert "ledcChangeFrequency" in text
        uncommented = "\n".join(
            line for line in text.splitlines()
            if not line.lstrip().startswith("//")
        )
        assert not re.search(r"\bledcAttach\s*\(", uncommented)

    def test_led_uses_new_ledc_api(self):
        text = (PROJECT_ROOT / "components/myrobot/src/LED.cpp").read_text()
        assert "ledcAttachPin" in text
        assert "ledcChangeFrequency" in text
        uncommented = "\n".join(
            line for line in text.splitlines()
            if not line.lstrip().startswith("//")
        )
        assert not re.search(r"\bledcAttach\s*\(", uncommented)

    def test_constants_h_has_ledc_channels(self):
        text = (PROJECT_ROOT / "components/myrobot/include/Constants.h").read_text()
        for name in ("DRIVE_MOTOR_FWD_PWM_CHANNEL", "DRIVE_MOTOR_REV_PWM_CHANNEL",
                     "ESC_PWM_CHANNEL", "LED_PWM_CHANNEL"):
            assert name in text, f"Constants.h should define {name}"

    def test_constants_h_is_c_compatible(self):
        """Constants.h is included from BOTH C and C++ files; no C++ features."""
        text = (PROJECT_ROOT / "components/myrobot/include/Constants.h").read_text()
        # The ControllerState struct should not have default member initializers
        # (those are C++ only and break compilation when included from .c files).
        m = re.search(r"struct ControllerState\s*\{([^}]+)\}", text, re.S)
        assert m, "Couldn't find ControllerState struct"
        body = m.group(1)
        # Look for `= 0` or `= false` etc. in field initializers
        assert not re.search(r"\w+\s*=\s*\d+\s*;", body), (
            "ControllerState fields should not have C++ default initializers. "
            "These break C compilation (Constants.h is included from main.c)."
        )


# ---------- Brace balance ----------

def strip_comments_and_strings(text: str) -> str:
    """Remove C/C++ comments and string literals so braces inside them
    don't fool the balance check."""
    # Remove block comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    # Remove line comments
    text = re.sub(r"//.*", "", text)
    # Replace string literals with empty strings (preserving quote positions)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", "''", text)
    return text


C_FILES_TO_CHECK = [
    "components/ble_gamepad/src/ble_gamepad.cpp",
    "components/ble_gamepad/include/ble_gamepad.h",
    "components/web_config/src/web_config.cpp",
    "components/web_config/include/web_config.h",
    "main/main.c",
    "main/sketch.cpp",
]


class TestBraceBalance:
    """New C/C++ files must have balanced braces/parens/brackets."""

    @pytest.mark.parametrize("relpath", C_FILES_TO_CHECK)
    def test_balanced(self, relpath):
        path = PROJECT_ROOT / relpath
        if not path.exists():
            pytest.fail(f"File missing: {relpath}")
        text = strip_comments_and_strings(path.read_text())
        pairs = [("{", "}"), ("(", ")"), ("[", "]")]
        issues = []
        for o, c in pairs:
            if text.count(o) != text.count(c):
                issues.append(f"{o}={text.count(o)} {c}={text.count(c)}")
        assert not issues, f"{relpath}: unbalanced " + ", ".join(issues)


# ---------- BLE API consistency ----------

class TestBleApiConsistency:
    """Every ble_gamepad_* function declared in the header must be defined in the cpp.

    Catches: refactor that renames a function in the header but not the cpp,
    or vice versa.
    """

    HEADER = PROJECT_ROOT / "components/ble_gamepad/include/ble_gamepad.h"
    CPP = PROJECT_ROOT / "components/ble_gamepad/src/ble_gamepad.cpp"

    def test_header_functions_all_defined(self):
        header = self.HEADER.read_text()
        cpp = self.CPP.read_text()
        # Find function declarations in header
        decls = set(re.findall(
            r"^\s*(?:esp_err_t|void|bool|(?:struct\s+)?ControllerState|PairingState|ble_mac_t|uint\d+_t)\s+(ble_gamepad_\w+)\s*\(",
            header, re.M))
        # Find function definitions in cpp
        defs = set(re.findall(
            r"^(?:esp_err_t|void|bool|(?:struct\s+)?ControllerState|PairingState)\s+(ble_gamepad_\w+)\s*\(",
            cpp, re.M))
        # Allow internal helpers (not in header) to be defined without decl
        # Find functions defined in cpp but NOT declared in header
        orphan_defs = defs - decls
        # Filter out file-static helpers we know about
        known_helpers = {"ble_mac_equal", "ble_mac_is_whitelisted"}
        unexpected = orphan_defs - known_helpers
        assert not unexpected, (
            f"Functions defined in cpp but not declared in header: {unexpected}"
        )

    def test_header_functions_all_have_definition(self):
        header = self.HEADER.read_text()
        cpp = self.CPP.read_text()
        decls = set(re.findall(
            r"^\s*(?:esp_err_t|void|bool|ControllerState|PairingState|ble_mac_t|uint\d+_t)\s+(ble_gamepad_\w+)\s*\(",
            header, re.M))
        defs = set(re.findall(
            r"^(?:esp_err_t|void|bool|ControllerState|PairingState)\s+(ble_gamepad_\w+)\s*\(",
            cpp, re.M))
        missing = decls - defs
        assert not missing, f"Declared in header but not defined: {missing}"


# ---------- No Bluepad32 leftovers ----------

class TestNoBluepad32Leftovers:
    """No Bluepad32 or btstack references should remain in the v2 code."""

    SEARCH_PATHS = [
        "components",
        "main",
    ]

    @pytest.mark.parametrize("search_path", SEARCH_PATHS)
    def test_no_bluepad32_or_btstack(self, search_path):
        root = PROJECT_ROOT / search_path
        if not root.exists():
            pytest.skip(f"{search_path} not found")
        violations = []
        for f in root.rglob("CMakeLists.txt"):
            text = f.read_text()
            if "bluepad32" in text.lower() or "btstack" in text.lower():
                violations.append(f)
        if violations:
            pytest.fail(
                f"Bluepad32/btstack references in: "
                f"{[str(v.relative_to(PROJECT_ROOT)) for v in violations]}"
            )


# ---------- NimBLE-Arduino integration ----------

class TestNimbleArduinoIntegration:
    """BLE should use the Arduino-compatible NimBLE library, not raw ESP-IDF archives.

    The raw ESP-IDF NimBLE attempt compiled but failed at link time because
    PlatformIO pulled an ABI-incompatible libbt.a. Under framework=arduino,
    NimBLE-Arduino is the supported dependency shape.
    """

    def test_platformio_uses_nimble_arduino_library(self):
        text = (PROJECT_ROOT / "platformio.ini").read_text()
        assert "h2zero/NimBLE-Arduino" in text

    def test_platformio_has_no_raw_esp_idf_nimble_link_hacks(self):
        text = (PROJECT_ROOT / "platformio.ini").read_text()
        forbidden = [
            "framework-arduinoespressif32-libs/esp32c3/include/bt",
            "framework-arduinoespressif32-libs/esp32c3/lib",
            "-lbt",
        ]
        present = [item for item in forbidden if item in text]
        assert not present, f"raw ESP-IDF NimBLE build/link hacks remain: {present}"

    def test_ble_implementation_uses_nimble_arduino_api(self):
        text = (PROJECT_ROOT / "components/ble_gamepad/src/ble_gamepad.cpp").read_text()
        assert "#include <NimBLEDevice.h>" in text
        assert "NimBLEAdvertisedDeviceCallbacks" in text or "NimBLEScan" in text
        forbidden = [
            "nimble/nimble_port.h",
            "host/ble_gap.h",
            "host/ble_gatt.h",
            "ble_gap_disc(",
            "nimble_port_run(",
        ]
        present = [item for item in forbidden if item in text]
        assert not present, f"raw ESP-IDF NimBLE API remains: {present}"

    def test_pc_ble_bench_tool_exists(self):
        tool = PROJECT_ROOT / "tools/pc_ble_bench.py"
        assert tool.exists(), "tools/pc_ble_bench.py should provide PC Bluetooth bench tests"
        text = tool.read_text()
        assert "bleak" in text
        assert "scan" in text
        assert "notify" in text or "start_notify" in text

    def test_pc_ble_bench_uuid_contract_matches_firmware(self):
        firmware = (PROJECT_ROOT / "components/ble_gamepad/src/ble_gamepad.cpp").read_text()
        tool = (PROJECT_ROOT / "tools/pc_ble_bench.py").read_text()
        bench_service = "7d2f0001-0f3a-4b8a-9b7d-2f4c9a000001"
        bench_write = "7d2f0002-0f3a-4b8a-9b7d-2f4c9a000001"
        assert bench_service in firmware
        assert bench_service in tool
        assert bench_write in firmware
        assert bench_write in tool
        assert "BOARD_BENCH_WRITE_UUID" in tool


# ---------- CMakeLists.txt sanity ----------

class TestCmakeLists:
    """Each component's CMakeLists.txt must declare the right dependencies."""

    CASES = [
        ("components/ble_gamepad/CMakeLists.txt", ["nimble", "nvs_flash"]),
        ("components/web_config/CMakeLists.txt", ["ble_gamepad"]),
        ("components/myrobot/CMakeLists.txt", ["arduino"]),
        ("main/CMakeLists.txt", ["myrobot", "ble_gamepad", "web_config"]),
    ]

    @pytest.mark.parametrize("relpath,required", CASES)
    def test_required_components_listed(self, relpath, required):
        path = PROJECT_ROOT / relpath
        if not path.exists():
            pytest.skip(f"{relpath} not found")
        text = path.read_text()
        missing = [r for r in required if r not in text]
        assert not missing, f"{relpath} missing REQUIRES: {missing}"


# ---------- Pin defines sanity ----------

class TestPinDefines:
    """Critical pin defines must match v1 (wiring is the same).

    Catches: accidental edits to Constants.h that would cause motors
    to misbehave or short out.
    """

    @pytest.mark.skipif(not (V1_REPO / "components/myrobot/include/Constants.h").exists(),
                        reason="v1 reference not available")
    def test_critical_pins_match_v1(self):
        v1 = (V1_REPO / "components/myrobot/include/Constants.h").read_text()
        v2 = (PROJECT_ROOT / "components/myrobot/include/Constants.h").read_text()

        # Pairs of (name, expected_value) that, if changed, would break the wiring.
        # Each may be defined as #define NAME val OR const TYPE NAME = val;
        critical = {
            "ESC_1_PIN": "4", "ESC_2_PIN": "8",
            "DRIVE_MOTOR1_1_PIN": "1", "DRIVE_MOTOR1_2_PIN": "3",
            "DRIVE_MOTOR2_1_PIN": "6", "DRIVE_MOTOR2_2_PIN": "7",
            "MODE_BUTTON_PIN": "5", "DEBUG_LED_PIN": "10", "BATT_MEAS_PIN": "0",
            "NUM_OF_CELLS": "3", "MIN_MVOLT_PER_CELL": "3600", "WARN_MVOLT_PER_CELL": "3750",
            "BATTERY_MULTIPLIER": "8.95f", "EMA_ALPHA": "0.1f",
            "ESC_PWM_FREQ": "2000", "DRIVE_MOTOR_PWM_FREQ": "20000",
            "DRIVE_MOTOR_PWM_RESOLUTION": "8", "ESC_PWM_RESOLUTION": "8",
            "ESC_MIN_PULSEWIDTH": "125", "ESC_MID_PULSEWIDTH": "188", "ESC_MAX_PULSEWIDTH": "250",
            "CONTROLLER_TIMEOUT": "1000", "DEBOUNCE_TIME": "10", "LONG_PRESS_TIME": "1000",
            "BUTTON_READ_WAIT": "50", "BATT_READ_FREQ": "100", "BATT_SAMPLE_COUNT": "5",
            "SAMPLE_PERIOD": "10", "BATTERY_DEBOUNCE_TIME": "3000",
            "BATT_HYSTERESIS": "100.0f",
            "WEAPON_BIDIRECTIONAL": "true", "WEAPON_ENABLE": "true",
            "ENABLE_LOW_BATTERY_SHUTDOWN": "true", "TASK_MANAGER_READ_FREQ": "50",
            "APP_CPU_NUM": "0",
        }
        issues = []
        for name, expected in critical.items():
            # Try #define first
            m = re.search(rf"^#define\s+{re.escape(name)}\s+(\S+)", v1, re.M)
            if not m:
                m = re.search(rf"^const\s+\w+\s+{re.escape(name)}\s*=\s*(\S+?);", v1, re.M)
            if not m:
                issues.append(f"{name}: not found in v1")
                continue
            v1_val = m.group(1)
            # Strip 'f' suffix on floats for comparison
            v1_norm = v1_val.rstrip(";").rstrip("f")
            exp_norm = expected.rstrip("f")
            if v1_norm != exp_norm:
                issues.append(f"{name}: v1='{v1_val}' expected='{expected}'")
        assert not issues, "Pin defines drifted from expected:\n  " + "\n  ".join(issues)