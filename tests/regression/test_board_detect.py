"""
Tests for the NVS-based board revision selection (board_detect.h/cpp).

What this catches:
  - The detection API surface is what callers expect
  - NVS namespace and key are consistent
  - Override path writes to NVS correctly
  - Clear path removes the override
  - The active_rev() function uses the right priority
  - Code structure (no orphan functions, no broken includes)

What this doesn't catch:
  - Real NVS persistence (requires flash + reboot on hardware)
  - The actual override being honored at runtime (requires integration test)
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

    def test_header_has_pragma_once(self):
        assert "#pragma once" in BOARD_DETECT_H.read_text()


# ---- API surface ----

class TestApiSurface:
    def test_boardrevid_enum(self):
        text = BOARD_DETECT_H.read_text()
        assert "enum BoardRevId" in text
        for name in ("BOARD_REV_ID_UNKNOWN", "BOARD_REV_ID_V2", "BOARD_REV_ID_V3"):
            assert name in text, f"BoardRevId missing {name}"

    def test_active_rev_function(self):
        text = BOARD_DETECT_H.read_text()
        assert "int board_detect_active_rev(void)" in text

    def test_id_to_rev_function(self):
        text = BOARD_DETECT_H.read_text()
        assert "int board_detect_id_to_rev(BoardRevId id)" in text

    def test_set_override_function(self):
        text = BOARD_DETECT_H.read_text()
        assert "esp_err_t board_detect_set_override(int rev)" in text

    def test_clear_override_function(self):
        text = BOARD_DETECT_H.read_text()
        assert "esp_err_t board_detect_clear_override(void)" in text

    def test_has_override_function(self):
        text = BOARD_DETECT_H.read_text()
        assert "bool board_detect_has_override(int *out_rev)" in text


# ---- NVS namespace and key ----

class TestNvsConfiguration:
    """The NVS namespace/key must be consistent between .h and .cpp."""

    def test_nvs_namespace_constant(self):
        cpp = BOARD_DETECT_CPP.read_text()
        # Namespace defined as a macro or constant
        assert "board_config" in cpp
        # Check it's used in nvs_open calls
        nvs_calls = re.findall(r'nvs_open\([^,]+,\s*[^,]+,\s*&', cpp)
        assert len(nvs_calls) >= 2, f"Expected 2+ nvs_open calls (set, get, clear), got {len(nvs_calls)}"

    def test_nvs_key_name(self):
        cpp = BOARD_DETECT_CPP.read_text()
        assert "rev_override" in cpp, "NVS key 'rev_override' not found"

    def test_get_i32_used_for_read(self):
        """Reading the override should use nvs_get_i32 (typed access)."""
        cpp = BOARD_DETECT_CPP.read_text()
        assert "nvs_get_i32" in cpp

    def test_set_i32_used_for_write(self):
        cpp = BOARD_DETECT_CPP.read_text()
        assert "nvs_set_i32" in cpp

    def test_erase_key_used_for_clear(self):
        cpp = BOARD_DETECT_CPP.read_text()
        assert "nvs_erase_key" in cpp


# ---- Priority order ----

class TestDetectionPriority:
    """active_rev() should: check NVS first, fall back to BOARD_REV."""

    def test_nvs_checked_first(self):
        cpp = BOARD_DETECT_CPP.read_text()
        # In active_rev(), has_override (which reads NVS) should be called
        # BEFORE the BOARD_REV fallback.
        m = re.search(r"int board_detect_active_rev\(void\)\s*\{(.*?)^\}", cpp, re.S | re.M)
        assert m, "board_detect_active_rev() body not found"
        body = m.group(1)
        has_override_pos = body.find("board_detect_has_override")
        board_rev_pos = body.find("return BOARD_REV")
        assert has_override_pos >= 0, "has_override not called in active_rev()"
        assert board_rev_pos >= 0, "BOARD_REV fallback not found in active_rev()"
        assert has_override_pos < board_rev_pos, (
            "NVS check (has_override) should happen BEFORE BOARD_REV fallback"
        )


# ---- Argument validation ----

class TestArgumentValidation:
    def test_set_override_validates_range(self):
        """set_override should reject out-of-range rev numbers."""
        cpp = BOARD_DETECT_CPP.read_text()
        # Should check the rev value is in a sensible range
        m = re.search(r"board_detect_set_override\(int rev\)\s*\{(.*?)return", cpp, re.S)
        assert m, "set_override function not found"
        body = m.group(1)
        # Should have some range check
        assert "ESP_ERR_INVALID_ARG" in body or "rev <" in body or "rev >" in body, (
            "set_override should validate rev range before writing to NVS"
        )


# ---- id_to_rev mapping ----

class TestIdToRevMapping:
    def test_v2_maps_to_2(self):
        cpp = BOARD_DETECT_CPP.read_text()
        m = re.search(r"case\s+BOARD_REV_ID_V2:\s*return\s+(\d+);", cpp)
        assert m and int(m.group(1)) == 2

    def test_v3_maps_to_3(self):
        cpp = BOARD_DETECT_CPP.read_text()
        m = re.search(r"case\s+BOARD_REV_ID_V3:\s*return\s+(\d+);", cpp)
        assert m and int(m.group(1)) == 3

    def test_unknown_maps_to_zero(self):
        """Unknown ID should return 0 (which is not a valid rev)."""
        cpp = BOARD_DETECT_CPP.read_text()
        m = re.search(r"default:\s*return\s+(\d+);", cpp)
        assert m and int(m.group(1)) == 0


# ---- Logging ----

class TestLogging:
    def test_set_override_logs(self):
        cpp = BOARD_DETECT_CPP.read_text()
        # The set function should log when override is set
        set_fn = re.search(r"board_detect_set_override\(.*?\n\}", cpp, re.S)
        assert set_fn, "set_override function not found"
        assert "ESP_LOGI" in set_fn.group(0) or "ESP_LOGW" in set_fn.group(0), (
            "set_override should log when override is set"
        )

    def test_clear_override_logs(self):
        cpp = BOARD_DETECT_CPP.read_text()
        clear_fn = re.search(r"board_detect_clear_override\(.*?\n\}", cpp, re.S)
        assert clear_fn, "clear_override function not found"
        assert "ESP_LOGI" in clear_fn.group(0), (
            "clear_override should log when override is cleared"
        )


# ---- What is NOT in this module (regression against Option 2) ----

class TestNoHardwareStrapping:
    """Per the user's design choice, hardware strapping detection is
    out of scope. Make sure it stays out."""

    def test_no_gpio_get_level(self):
        """Should not have any GPIO reading (we removed hardware strapping)."""
        cpp = BOARD_DETECT_CPP.read_text()
        assert "gpio_get_level" not in cpp, (
            "Hardware strapping code should not be in this module. "
            "We chose NVS-only detection (Option 1). If you want to "
            "re-enable hardware detection, do it explicitly and update tests."
        )

    def test_no_board_id_gpio_pins(self):
        """Should not have BOARD_ID_GPIO0/1 macros (those were for strapping)."""
        h = BOARD_DETECT_H.read_text()
        assert "BOARD_ID_GPIO0" not in h, (
            "BOARD_ID_GPIO0/1 are for hardware strapping. "
            "If you need them, add them as a separate module."
        )
        assert "BOARD_ID_GPIO1" not in h


# ---- Required ESP-IDF dependencies ----

class TestDependencies:
    def test_cmake_dependencies(self):
        cmake = (PROJECT_ROOT / "components/board_config/CMakeLists.txt").read_text()
        for dep in ("nvs_flash", "esp_log"):
            assert dep in cmake, f"CMakeLists.txt missing {dep} requirement"


# ---- Integration with board_config.h ----

class TestIntegrationWithBoardConfig:
    """board_detect.h should include board_config.h so BOARD_REV is available."""

    def test_includes_board_config(self):
        text = BOARD_DETECT_H.read_text()
        assert '#include "board_config.h"' in text, (
            "board_detect.h must include board_config.h to access BOARD_REV"
        )

    def test_active_rev_returns_board_rev(self):
        """active_rev() should return BOARD_REV when no NVS override."""
        cpp = BOARD_DETECT_CPP.read_text()
        m = re.search(r"int board_detect_active_rev\(void\)\s*\{(.*?)^\}", cpp, re.S | re.M)
        assert m
        body = m.group(1)
        # The fallback should return BOARD_REV
        assert "return BOARD_REV" in body