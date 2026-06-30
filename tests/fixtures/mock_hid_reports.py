"""
Mock HID gamepad report generator for tests.

Produces synthetic standard Bluetooth HID gamepad reports. These are byte
sequences representing what a real 8BitDo / Gamesir / ipega sends over BLE
when in HID gamepad mode.

The format is the standard Bluetooth HID gamepad report (per the Bluetooth
HID spec, used by 8BitDo Ultimate / Pro 2 in BLE mode):

  byte 0: X         (left stick X, 0..255, center=127)
  byte 1: Y         (left stick Y, 0..255, center=127)
  byte 2: Z         (right stick X, 0..255, center=127)
  byte 3: Rz        (right stick Y, 0..255, center=127)
  byte 4-5: buttons (16-bit, little-endian)
  byte 6: Rz analog (L2 trigger, 0..255)
  byte 7: Ry analog (R2 trigger, 0..255)
  byte 8: hat switch (0..7=N..NW, 8=center, 15=released)

Button bit positions (per Bluetooth HID standard, matches BP32):
  bit 0:  A (B on Xbox / cross on PS)
  bit 1:  B (A on Xbox / circle on PS)
  bit 2:  X (X on Xbox / square on PS)
  bit 3:  Y (Y on Xbox / triangle on PS)
  bit 4:  L1
  bit 5:  R1
  bit 6:  L2 (digital)
  bit 7:  R2 (digital)
  bit 8:  SELECT/SHARE/-
  bit 9:  START/OPTIONS/+
  bit 10: L3
  bit 11: R3
  bit 12: HOME
"""


def make_report(
    x=127, y=127, z=127, rz=127,
    buttons=0,
    l2=0, r2=0,
    hat=15,  # 15 = released (no direction)
    extra=b"",
):
    """Build a single HID report byte sequence.

    Defaults: sticks centered, no buttons pressed, triggers released, dpad
    neutral. Pass overrides for any state.
    """
    lo = buttons & 0xFF
    hi = (buttons >> 8) & 0xFF
    return bytes([x, y, z, rz, lo, hi, l2, r2, hat]) + bytes(extra)


# Pre-built states for common test scenarios.
# These are what we'd capture from a real 8BitDo using a BLE sniffer.

IDLE = make_report()  # All centered, no buttons
STICKS_NEUTRAL = make_report(x=127, y=127, z=127, rz=127)


def left_stick_full_forward():
    """Left stick pushed all the way forward (Y=0 in HID = up)."""
    return make_report(y=0)


def left_stick_full_back():
    """Left stick pulled all the way back (Y=255 in HID = down)."""
    return make_report(y=255)


def right_trigger_full():
    """Right trigger fully pressed (R2=255)."""
    return make_report(r2=255)


def left_trigger_full():
    """Left trigger fully pressed (L2=255)."""
    return make_report(l2=255)


def a_pressed():
    """A button held (bit 0)."""
    return make_report(buttons=(1 << 0))


def y_pressed():
    """Y button held (bit 3). This is the orientation-flip button in TaskManager."""
    return make_report(buttons=(1 << 3))


def all_face_buttons():
    """A, B, X, Y all held."""
    return make_report(buttons=(1 << 0) | (1 << 1) | (1 << 2) | (1 << 3))


# Hat switch values: 0..7 are directions, 8 = center, 15 = released.
HAT_NORTH = 0
HAT_NORTHEAST = 1
HAT_EAST = 2
HAT_SOUTHEAST = 3
HAT_SOUTH = 4
HAT_SOUTHWEST = 5
HAT_WEST = 6
HAT_NORTHWEST = 7
HAT_CENTER = 8
HAT_RELEASED = 15


def dpad_north():
    return make_report(hat=HAT_NORTH)


def dpad_south():
    return make_report(hat=HAT_SOUTH)


def dpad_east():
    return make_report(hat=HAT_EAST)


def dpad_west():
    return make_report(hat=HAT_WEST)


def dpad_northeast():
    return make_report(hat=HAT_NORTHEAST)


# Edge cases for input validation.

def short_report():
    """Shorter than 8 bytes — should be rejected by the parser."""
    return bytes([0x10, 0x20, 0x30])


def min_length_report():
    """Exactly 8 bytes — minimum the parser accepts (no dpad/triggers)."""
    return bytes([127, 127, 127, 127, 0, 0, 0, 0])


def all_axes_max():
    """All axes at max — edge case for scaling math."""
    return make_report(x=0, y=0, z=0, rz=0)


def all_axes_min():
    """All axes at min — edge case for scaling math."""
    return make_report(x=255, y=255, z=255, rz=255)


def all_buttons_set():
    """All 16 button bits set — edge case for bitmask handling."""
    return make_report(buttons=0xFFFF)