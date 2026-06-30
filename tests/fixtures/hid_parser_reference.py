"""
Reference Python implementation of the HID report parser.

This is a SPECIFICATION CAPTURE of the behavior the C++ code in
components/ble_gamepad/src/ble_gamepad.cpp::parse_hid_report() must
implement. The C++ function is a copy of this logic (with type
differences: int vs int16_t, etc).

When the C++ code drifts from this spec, the C++ behavior is "bug" and
this file is "documentation." When in doubt, this is the truth.

If you change the C++ parser, you MUST update this file to match, and
add a test that covers the change. Otherwise the unit tests below will
fail to detect future regressions.

See: components/ble_gamepad/src/ble_gamepad.cpp lines ~270-320 for the
C++ implementation.
"""

# BP32-style axis range that the C++ code remaps to. ControllerState
# struct (in myrobot/Constants.h) and TaskManager both expect this scale.
AXIS_MIN = -512
AXIS_MAX = 511

# Standard HID center value.
AXIS_CENTER_HID = 127

# Multiplier used to remap 0..255 → BP32-style range.
# (v - 127) * 4 gives -508..508, which is "close enough" — see comment
# in C++ source for why this isn't exact -511..511.
AXIS_SCALE = 4

# Trigger scale: HID reports 0..255; BP32 reports 0..1023.
TRIGGER_SCALE = 4

# Dpad bitmask (matches BP32).
DPAD_UP = 0x01
DPAD_DOWN = 0x02
DPAD_LEFT = 0x04
DPAD_RIGHT = 0x08


def parse_hid_report(data: bytes) -> dict:
    """Parse a standard Bluetooth HID gamepad report.

    Returns a dict with the same fields as myrobot::ControllerState.
    On a too-short report, returns an "all zero" state — matches the
    C++ behavior of `if (len < 8) return;` which leaves the previous
    state unchanged in the global. We instead return zeros for test
    predictability.

    For the C++ implementation, the function MUTATES the global
    controller_state. In Python we return a new dict so tests can
    compare directly.
    """
    result = {
        "leftStickX": 0,
        "leftStickY": 0,
        "rightStickX": 0,
        "rightStickY": 0,
        "leftTrigger": 0,
        "rightTrigger": 0,
        "buttons": 0,
        "dpad": 0,
    }

    if len(data) < 8:
        return result  # C++ returns without modifying; we return zeros

    # Axes: (v - 127) * 4 → -508..508.
    # C++: int scale_axis_full = [](uint8_t v) { return ((int)v - 127) * 4; };
    result["leftStickX"] = (data[0] - AXIS_CENTER_HID) * AXIS_SCALE
    result["leftStickY"] = (data[1] - AXIS_CENTER_HID) * AXIS_SCALE
    result["rightStickX"] = (data[2] - AXIS_CENTER_HID) * AXIS_SCALE
    result["rightStickY"] = (data[3] - AXIS_CENTER_HID) * AXIS_SCALE

    # Buttons: little-endian 16-bit at offset 4.
    if len(data) >= 6:
        result["buttons"] = data[4] | (data[5] << 8)

    # Triggers: byte 6 = L2, byte 7 = R2.
    if len(data) >= 8:
        result["leftTrigger"] = data[6] * TRIGGER_SCALE
        result["rightTrigger"] = data[7] * TRIGGER_SCALE

    # Dpad: byte 8, hat switch 0..7 or 8 (center) or 15 (released).
    if len(data) >= 9:
        hat = data[8]
        result["dpad"] = _hat_to_dpad(hat)

    return result


def _hat_to_dpad(hat: int) -> int:
    """Translate a Bluetooth HID hat switch value to a BP32-style dpad mask.

    Hat switch encoding (per Bluetooth HID spec):
      0=N, 1=NE, 2=E, 3=SE, 4=S, 5=SW, 6=W, 7=NW
      8 = center (no direction)
      15 = released (also no direction; some controllers report this)
    """
    if hat == 0:  # N → up
        return DPAD_UP
    elif hat == 1:  # NE → up + right
        return DPAD_UP | DPAD_RIGHT
    elif hat == 2:  # E → right
        return DPAD_RIGHT
    elif hat == 3:  # SE → down + right
        return DPAD_DOWN | DPAD_RIGHT
    elif hat == 4:  # S → down
        return DPAD_DOWN
    elif hat == 5:  # SW → down + left
        return DPAD_DOWN | DPAD_LEFT
    elif hat == 6:  # W → left
        return DPAD_LEFT
    elif hat == 7:  # NW → up + left
        return DPAD_UP | DPAD_LEFT
    else:  # 8 = center, 15 = released, anything else = unknown → 0
        return 0