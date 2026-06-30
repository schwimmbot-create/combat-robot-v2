"""
Tests for the HID report parser.

These tests exercise the REFERENCE Python implementation in
fixtures/hid_parser_reference.py. The C++ implementation in
components/ble_gamepad/src/ble_gamepad.cpp::parse_hid_report() MUST
match this behavior. If you change the C++ parser, you must also
update the reference and add a test for the new behavior.

What this catches:
  - Axis scaling math (e.g. (127 - 127) * 4 == 0, not 1)
  - Button bit ordering (LE vs BE — common bug)
  - Hat switch translation (most controllers report N=0, but some
    report N=1; a 1-off-by-one would silently break dpad)
  - Short-report handling (parser must not crash on <8 bytes)
  - Edge cases: max/min values, all buttons set

What this doesn't catch:
  - Real BLE behavior (GATT discovery, notifications, etc.)
  - Per-controller quirks (some 8BitDo models report hat differently)
"""
import pytest

from fixtures.hid_parser_reference import (
    parse_hid_report,
    _hat_to_dpad,
    DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT,
    AXIS_CENTER_HID, AXIS_SCALE,
)
from fixtures.mock_hid_reports import (
    IDLE, STICKS_NEUTRAL,
    left_stick_full_forward, left_stick_full_back,
    right_trigger_full, left_trigger_full,
    a_pressed, y_pressed, all_face_buttons,
    dpad_north, dpad_south, dpad_east, dpad_west, dpad_northeast,
    short_report, min_length_report,
    all_axes_max, all_axes_min, all_buttons_set,
    HAT_NORTH, HAT_SOUTH, HAT_EAST, HAT_WEST, HAT_CENTER, HAT_RELEASED,
)


# ---------- Axis scaling ----------

class TestAxisScaling:
    """Verify the (v - 127) * 4 axis remap."""

    def test_center_is_zero(self):
        """Stick at HID center (127) should map to 0."""
        r = parse_hid_report(STICKS_NEUTRAL)
        assert r["leftStickX"] == 0
        assert r["leftStickY"] == 0
        assert r["rightStickX"] == 0
        assert r["rightStickY"] == 0

    def test_full_forward(self):
        """Left stick full forward: HID Y=0 → BP32 -508 (negative = up/forward)."""
        r = parse_hid_report(left_stick_full_forward())
        # (0 - 127) * 4 = -508
        assert r["leftStickY"] == -508

    def test_full_back(self):
        """Left stick full back: HID Y=255 → BP32 +508 (positive = down/back)."""
        r = parse_hid_report(left_stick_full_back())
        # (255 - 127) * 4 = +512
        assert r["leftStickY"] == 512

    def test_all_axes_max_produces_extreme_negative(self):
        """All axes at 0 (full forward) should give min on all sticks."""
        r = parse_hid_report(all_axes_max())
        expected = -127 * AXIS_SCALE
        assert r["leftStickX"] == expected
        assert r["leftStickY"] == expected
        assert r["rightStickX"] == expected
        assert r["rightStickY"] == expected

    def test_all_axes_min_produces_extreme_positive(self):
        """All axes at 255 (full back/right) should give max on all sticks."""
        r = parse_hid_report(all_axes_min())
        expected = (255 - AXIS_CENTER_HID) * AXIS_SCALE
        assert r["leftStickX"] == expected
        assert r["leftStickY"] == expected
        assert r["rightStickX"] == expected
        assert r["rightStickY"] == expected

    def test_axis_symmetry(self):
        """Pushing stick to opposite extremes should produce equal-magnitude opposite values.

        This catches sign-flip bugs. If you write the C++ parser wrong
        and use 255-v instead of v-127, this test fails.
        """
        fwd = parse_hid_report(left_stick_full_forward())["leftStickY"]
        back = parse_hid_report(left_stick_full_back())["leftStickY"]
        # Not exactly equal (HID goes 0..255 but linear remap gives
        # -508..+512, off by 4). Close enough.
        assert fwd == -508
        assert back == 512
        assert fwd + back == 4  # asymmetry of 4 (see comment in C++)

    def test_one_above_center(self):
        """Stick at HID 128 should give +4 (one step forward of center)."""
        from fixtures.mock_hid_reports import make_report
        r = parse_hid_report(make_report(y=128))
        assert r["leftStickY"] == 4

    def test_one_below_center(self):
        """Stick at HID 126 should give -4 (one step back from center)."""
        from fixtures.mock_hid_reports import make_report
        r = parse_hid_report(make_report(y=126))
        assert r["leftStickY"] == -4


# ---------- Buttons ----------

class TestButtons:
    """Verify the 16-bit button bitmask parsing."""

    def test_no_buttons(self):
        r = parse_hid_report(IDLE)
        assert r["buttons"] == 0

    def test_a_button_bit_0(self):
        """A is bit 0 (per BP32 / Bluetooth HID spec)."""
        r = parse_hid_report(a_pressed())
        assert r["buttons"] == 0x0001

    def test_y_button_bit_3(self):
        """Y is bit 3. TaskManager::processButtons() uses this for orientation flip.

        If the C++ parser swaps Y with B (common copy-paste bug), this fails.
        """
        r = parse_hid_report(y_pressed())
        assert r["buttons"] == 0x0008  # 1 << 3

    def test_all_face_buttons(self):
        r = parse_hid_report(all_face_buttons())
        assert r["buttons"] == 0x000F  # bits 0-3

    def test_all_16_buttons(self):
        """All 16 button bits set — edge case."""
        r = parse_hid_report(all_buttons_set())
        assert r["buttons"] == 0xFFFF

    def test_little_endian_byte_order(self):
        """Buttons are stored little-endian: low byte first, high byte second.

        C++ code does: data[4] | (data[5] << 8).
        If the C++ accidentally swaps to (data[4] << 8) | data[5], the
        high byte is in the wrong place and all 16-bit masks are wrong.
        """
        from fixtures.mock_hid_reports import make_report
        # Build a report with buttons=0x1234.
        # Should encode as byte[4]=0x34, byte[5]=0x12.
        r = parse_hid_report(make_report(buttons=0x1234))
        assert r["buttons"] == 0x1234

    def test_high_byte_only(self):
        """Buttons with only the high byte set (bit 8 = SELECT).

        Catches: (data[4] << 8) | data[5] bug — would put high byte in wrong slot.
        """
        from fixtures.mock_hid_reports import make_report
        r = parse_hid_report(make_report(buttons=0x0100))  # only bit 8
        assert r["buttons"] == 0x0100


# ---------- Triggers ----------

class TestTriggers:
    """Verify L2/R2 trigger parsing and BP32-style scaling (×4)."""

    def test_no_triggers(self):
        r = parse_hid_report(IDLE)
        assert r["leftTrigger"] == 0
        assert r["rightTrigger"] == 0

    def test_right_trigger_full(self):
        """HID R2=255 → BP32 1020 (not 1023; off by 3, documented in C++)."""
        r = parse_hid_report(right_trigger_full())
        assert r["rightTrigger"] == 1020  # 255 * 4

    def test_left_trigger_full(self):
        r = parse_hid_report(left_trigger_full())
        assert r["leftTrigger"] == 1020

    def test_trigger_half(self):
        """HID 128 → BP32 512."""
        from fixtures.mock_hid_reports import make_report
        r = parse_hid_report(make_report(l2=128, r2=128))
        assert r["leftTrigger"] == 512
        assert r["rightTrigger"] == 512


# ---------- Dpad / hat switch ----------

class TestDpadHatSwitch:
    """Verify hat switch → BP32 dpad bitmask translation.

    The 8BitDo and most BLE gamepads use the standard Bluetooth HID hat
    switch encoding. Some controllers (e.g. certain 8BitDo models in
    specific modes) report differently. If your test fails on real
    hardware, check that the controller is in standard HID mode.
    """

    def test_helpers(self):
        """Internal: the helper function maps each direction correctly."""
        assert _hat_to_dpad(0) == DPAD_UP
        assert _hat_to_dpad(2) == DPAD_RIGHT
        assert _hat_to_dpad(4) == DPAD_DOWN
        assert _hat_to_dpad(6) == DPAD_LEFT
        # Diagonals
        assert _hat_to_dpad(1) == (DPAD_UP | DPAD_RIGHT)
        assert _hat_to_dpad(3) == (DPAD_DOWN | DPAD_RIGHT)
        assert _hat_to_dpad(5) == (DPAD_DOWN | DPAD_LEFT)
        assert _hat_to_dpad(7) == (DPAD_UP | DPAD_LEFT)

    def test_dpad_north(self):
        r = parse_hid_report(dpad_north())
        assert r["dpad"] == DPAD_UP
        assert r["dpad"] == 0x01

    def test_dpad_south(self):
        r = parse_hid_report(dpad_south())
        assert r["dpad"] == DPAD_DOWN
        assert r["dpad"] == 0x02

    def test_dpad_east(self):
        r = parse_hid_report(dpad_east())
        assert r["dpad"] == DPAD_RIGHT
        assert r["dpad"] == 0x08

    def test_dpad_west(self):
        r = parse_hid_report(dpad_west())
        assert r["dpad"] == DPAD_LEFT
        assert r["dpad"] == 0x04

    def test_dpad_diagonal_ne(self):
        r = parse_hid_report(dpad_northeast())
        assert r["dpad"] == (DPAD_UP | DPAD_RIGHT)

    def test_dpad_center_is_zero(self):
        from fixtures.mock_hid_reports import make_report
        r = parse_hid_report(make_report(hat=HAT_CENTER))
        assert r["dpad"] == 0

    def test_dpad_released_is_zero(self):
        """Some controllers report 15 = "released" when dpad is idle."""
        from fixtures.mock_hid_reports import make_report
        r = parse_hid_report(make_report(hat=HAT_RELEASED))
        assert r["dpad"] == 0

    def test_hat_does_not_affect_buttons(self):
        """Pressing dpad should NOT set any button bits."""
        r = parse_hid_report(dpad_north())
        assert r["buttons"] == 0


# ---------- Edge cases / robustness ----------

class TestEdgeCases:
    """Parser must not crash on malformed input."""

    def test_short_report_returns_zeros(self):
        """A report shorter than 8 bytes returns an all-zero state.

        The C++ implementation `if (len < 8) return;` would leave the
        previous state unchanged. Python reference returns zeros for
        test predictability — both are valid, but the C++ behavior is
        "don't update" which in real life means the previous valid state
        stays in place until a full report arrives.
        """
        r = parse_hid_report(short_report())
        assert r == {
            "leftStickX": 0, "leftStickY": 0,
            "rightStickX": 0, "rightStickY": 0,
            "leftTrigger": 0, "rightTrigger": 0,
            "buttons": 0, "dpad": 0,
        }

    def test_empty_report(self):
        r = parse_hid_report(b"")
        assert r["buttons"] == 0

    def test_min_length_report_no_dpad(self):
        """8-byte report: axes + buttons + triggers, but no dpad byte.

        Should still parse axes, buttons, triggers; dpad stays 0.
        """
        r = parse_hid_report(min_length_report())
        assert r["leftStickX"] == 0  # 127 - 127 = 0
        assert r["leftStickY"] == 0
        assert r["buttons"] == 0
        assert r["leftTrigger"] == 0
        assert r["rightTrigger"] == 0
        assert r["dpad"] == 0  # no byte 8, stays default

    def test_long_report_extra_bytes_ignored(self):
        """Reports longer than 9 bytes (some controllers append vendor data).

        C++ code reads data[0..8] only, ignores the rest. Python should
        do the same.
        """
        from fixtures.mock_hid_reports import make_report
        report = make_report(buttons=0x0001, hat=2) + bytes([0xDE, 0xAD, 0xBE, 0xEF])
        r = parse_hid_report(report)
        assert r["buttons"] == 0x0001
        assert r["dpad"] == DPAD_RIGHT
        # Extra bytes are ignored, no exception

    def test_max_value_axes_doesnt_overflow_python(self):
        """Sanity check: extreme values don't break Python (which has
        arbitrary precision ints). The C++ code uses `int` (32-bit),
        so values stay well within range.
        """
        r = parse_hid_report(all_axes_min())
        # (255 - 127) * 4 = 512
        assert r["leftStickX"] == 512
        # Confirm it's not negative due to wraparound
        assert r["leftStickX"] > 0


# ---------- ProcessButtons integration contract ----------

class TestProcessButtonsContract:
    """Verify the contract between HID parser output and TaskManager.

    TaskManager::processButtons() in components/myrobot/src/TaskManager.cpp
    reads specific button bits. If the parser produces wrong bit positions,
    processButtons() will trigger the wrong actions (e.g. orientation
    flip when user presses A instead of Y).
    """

    def test_orientation_flip_button(self):
        """Y (bit 3) should trigger orientation flip.

        See TaskManager::processButtons():
            if( prevY == 0 && Y == 1 ){ flipOrientation(); }
        """
        r = parse_hid_report(y_pressed())
        # Y is bit 3, so (buttons >> 3) & 0x01 should be 1
        assert ((r["buttons"] >> 3) & 0x01) == 1

    def test_a_button_does_not_trigger_orientation_flip(self):
        """Pressing A (bit 0) should NOT have bit 3 set.

        Catches: bit-shift-off-by-one bugs in the C++ parser.
        """
        r = parse_hid_report(a_pressed())
        assert ((r["buttons"] >> 3) & 0x01) == 0

    def test_b_button_bit_1(self):
        """B is bit 1 — used for LED toggle in v1.3 processGamepad()."""
        from fixtures.mock_hid_reports import make_report
        r = parse_hid_report(make_report(buttons=(1 << 1)))
        assert ((r["buttons"] >> 1) & 0x01) == 1

    def test_x_button_bit_2(self):
        """X is bit 2 — used for rumble in v1.3 processGamepad()."""
        from fixtures.mock_hid_reports import make_report
        r = parse_hid_report(make_report(buttons=(1 << 2)))
        assert ((r["buttons"] >> 2) & 0x01) == 1