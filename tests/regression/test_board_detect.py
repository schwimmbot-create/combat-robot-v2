"""
Tests for the runtime board detection module (board_detect.h/cpp).

What this catches:
  - The detection API surface (functions, enums, macros) is what callers expect
  - The BOARD_ID_GPIO0/1 pin choices are valid (not used by other peripherals)
  - The board ID encoding (0b00 = v2, 0b01 = v3, etc.) is consistent
  - The runtime override path (NVS) is wired up
  - The fallback path (compile-time BOARD_REV) is documented

What this doesn't catch:
  - Actual GPIO hardware behavior (requires ESP32 to run)
  - Real NVS persistence (requires flash)
"""
import re
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BOARD_DETECT_H = PROJECT_ROOT / "components/board_config/include/board_detect.h"
BOARD_DETECT_CPP = PROJECT_ROOT / "components/board_config/src/board_detect.cpp"
BOARD_CONFIG_H = PROJECT_ROOT / "components/board_config/include/board_config.h"


# ---- File existence ----

class TestFileExists:
    def test_header_exists(self):
        assert BOARD_DETECT_H.exists(), "board_detect.h missing"

    def test_implementation_exists(self):
        assert BOARD_DETECT_CPP.exists(), "board_detect.cpp missing"

    def test_header_includes_pragma_once(self):
        assert "#pragma once" in BOARD_DETECT_H.read_text()


# ---- API surface ----

class TestApiSurface:
    """The detection API must be what callers expect."""

    def test_boardrevid_enum(self):
        text = BOARD_DETECT_H.read_text()
        assert "enum BoardRevId" in text
        # Must have at least v2 and v3, plus UNKNOWN
        for name in ("BOARD_REV_ID_UNKNOWN", "BOARD_REV_ID_V2", "BOARD_REV_ID_V3"):
            assert name in text, f"BoardRevId missing {name}"

    def test_init_function(self):
        text = BOARD_DETECT_H.read_text()
        assert "void board_detect_init(void)" in text

    def test_read_id_function(self):
        text = BOARD_DETECT_H.read_text()
        assert "BoardRevId board_detect_read_id(void)" in text

    def test_id_to_rev_function(self):
        text = BOARD_DETECT_H.read_text()
        assert "int board_detect_id_to_rev(BoardRevId id)" in text

    def test_active_rev_function(self):
        text = BOARD_DETECT_H.read_text()
        assert "int board_detect_active_rev(void)" in text

    def test_override_setters(self):
        text = BOARD_DETECT_H.read_text()
        # These are in the .cpp (not .h) but should be referenced
        # for testing the override path
        cpp = BOARD_DETECT_CPP.read_text()
        assert "board_detect_set_override" in cpp
        assert "board_detect_clear_override" in cpp


# ---- Pin choices ----

class TestPinChoices:
    """The BOARD_ID pins must be valid (not used by other peripherals)."""

    def test_board_id_pins_defined(self):
        text = BOARD_DETECT_H.read_text()
        assert "BOARD_ID_GPIO0" in text
        assert "BOARD_ID_GPIO1" in text

    def test_board_id_pins_not_strapping(self):
        """ID pins must not be ESP32-C3 strapping pins (would affect boot).

        ESP32-C3 strapping pins: GPIO2, GPIO8, GPIO9.
        The strapping pins determine boot mode (download vs run).
        We must NOT use these for board ID.
        """
        text = BOARD_DETECT_H.read_text()
        for pin_match in re.finditer(r"#define\s+BOARD_ID_GPIO(\d+)\s+(\d+)", text):
            pin_num = int(pin_match.group(2))
            assert pin_num not in (2, 8, 9), (
                f"BOARD_ID_GPIO{pin_match.group(1)} = {pin_num} is a "
                "strapping pin (GPIO2/8/9). DO NOT use for board ID — "
                "this would affect boot mode!"
            )

    def test_board_id_pins_not_used_by_board_config(self):
        """ID pins must not be in board_config.h's pin assignments."""
        # Get all PIN_* values from board_config.h
        config_text = BOARD_CONFIG_H.read_text()
        used_pins = set()
        for m in re.finditer(r"#define\s+PIN_\w+\s+(\d+)", config_text):
            pin = int(m.group(1))
            if 0 <= pin <= 21:  # valid GPIO range
                used_pins.add(pin)

        # Check the ID pins aren't in there
        detect_text = BOARD_DETECT_H.read_text()
        for pin_match in re.finditer(r"#define\s+BOARD_ID_GPIO(\d+)\s+(\d+)", detect_text):
            pin_num = int(pin_match.group(2))
            if pin_num == 255:
                continue  # "Invalid" sentinel
            assert pin_num not in used_pins, (
                f"BOARD_ID_GPIO{pin_match.group(1)} = {pin_num} is already used "
                f"by board_config.h (used pins: {sorted(used_pins)}). "
                "Choose a free GPIO for the ID pin."
            )


# ---- ID encoding ----

class TestIdEncoding:
    """The 2-bit ID encoding (0b00 = v2, etc.) must be consistent
    between the .h and .cpp files."""

    def test_id_to_rev_returns_correct_values(self):
        cpp = BOARD_DETECT_CPP.read_text()
        # The switch in board_detect_id_to_rev should map each ID to a rev number
        for id_const, expected_rev in (
            ("BOARD_REV_ID_V2", 2),
            ("BOARD_REV_ID_V3", 3),
        ):
            # Look for: case BOARD_REV_ID_V2: return 2;
            m = re.search(rf"case\s+{id_const}:\s*return\s+(\d+);", cpp)
            assert m, f"{id_const} case not found in id_to_rev"
            assert int(m.group(1)) == expected_rev, (
                f"{id_const} should return {expected_rev}, got {m.group(1)}"
            )

    def test_unknown_returns_zero(self):
        """BoardRevId::UNKNOWN should map to 0 (which is BOARD_REV_ID_UNKNOWN)."""
        cpp = BOARD_DETECT_CPP.read_text()
        m = re.search(r"default:\s*return\s+(\d+);", cpp)
        assert m, "default case in id_to_rev not found"
        assert int(m.group(1)) == 0


# ---- Detection priority ----

class TestDetectionPriority:
    """The detection order is: NVS > hardware > compile-time."""

    def test_nvs_checked_first(self):
        """In board_detect_init(), NVS check should happen BEFORE hardware read.

        We extract just the body of init() to avoid the false positive
        from the function-definition line of board_detect_read_id.
        """
        cpp = BOARD_DETECT_CPP.read_text()
        # Find the body of init()
        m = re.search(r"void board_detect_init\(void\)\s*\{(.*?)^\}", cpp, re.S | re.M)
        assert m, "board_detect_init() body not found"
        init_body = m.group(1)
        nvs_pos = init_body.find("nvs_open")
        read_id_pos = init_body.find("board_detect_read_id()")
        assert nvs_pos >= 0, "nvs_open not called in init()"
        assert read_id_pos >= 0, "board_detect_read_id() not called in init()"
        assert nvs_pos < read_id_pos, (
            "NVS should be checked BEFORE hardware strapping read in init()"
        )

    def test_compile_time_fallback_present(self):
        """If NVS and hardware both fail, fall back to BOARD_REV."""
        cpp = BOARD_DETECT_CPP.read_text()
        assert "BOARD_REV" in cpp, "Compile-time fallback to BOARD_REV not found"
        # Find the fallback line
        m = re.search(r"s_active_rev\s*=\s*BOARD_REV\s*;", cpp)
        assert m, "Compile-time fallback assignment not found"


# ---- NVS namespace ----

class TestNvsNamespace:
    """The NVS namespace for board config should be consistent."""

    def test_nvs_namespace_name(self):
        cpp = BOARD_DETECT_CPP.read_text()
        # The namespace should be a specific name we can test
        assert '"board_config"' in cpp, "NVS namespace 'board_config' not found"
        # The key should be a specific name
        assert '"rev_override"' in cpp, "NVS key 'rev_override' not found"


# ---- Logging ----

class TestLogging:
    """The detection should log what it found."""

    def test_init_logs(self):
        cpp = BOARD_DETECT_CPP.read_text()
        # Should log start of detection
        assert "ESP_LOGI" in cpp, "No ESP_LOGI in board_detect.cpp"
        # Should log the result
        assert "Detected" in cpp or "Detected board" in cpp

    def test_warning_on_failure(self):
        cpp = BOARD_DETECT_CPP.read_text()
        # Should warn if detection fails
        assert "ESP_LOGW" in cpp, "No ESP_LOGW for detection failure"


# ---- Required ESP-IDF dependencies ----

class TestDependencies:
    """The detection module needs NVS, GPIO driver, and logging."""

    def test_cmake_dependencies(self):
        cmake = (PROJECT_ROOT / "components/board_config/CMakeLists.txt").read_text()
        # Should require nvs_flash and driver
        for dep in ("nvs_flash", "driver", "esp_log"):
            assert dep in cmake, f"CMakeLists.txt missing {dep} requirement"