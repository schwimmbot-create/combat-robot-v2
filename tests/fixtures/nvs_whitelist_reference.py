"""
Reference Python implementation of the NVS whitelist logic.

The C++ code in components/ble_gamepad/src/ble_gamepad.cpp implements
this against the real NVS flash storage. This file replicates the
SAME behavior in Python using a dict-based mock, so the unit tests
can exercise the logic without flashing firmware.

API surface (must match ble_gamepad.h public API):
  - add(mac)           -> True if added, False if already there or full
  - remove(mac)        -> True if removed, False if not present
  - clear()            -> empties the whitelist
  - is_whitelisted(mac) -> bool
  - count()            -> number of stored MACs
  - get_all()          -> list of stored MACs (in insertion order)

Capacity: BLE_MAX_PAIRED_CONTROLLERS = 4 (defined in ble_gamepad.h).

The C++ implementation uses NVS blobs, not a contiguous array. The
public API contract is what matters — both must support up to 4
whitelisted MACs, add/remove/clear/is_whitelisted, and return the
correct count.

See: components/ble_gamepad/src/ble_gamepad.cpp::nvs_*_mac and
     components/ble_gamepad/src/ble_gamepad.cpp::ble_gamepad_*_mac
"""

# Must match components/ble_gamepad/include/ble_gamepad.h
BLE_MAX_PAIRED_CONTROLLERS = 4


def mac_equal(a: bytes, b: bytes) -> bool:
    """Compare two 6-byte MAC addresses. Order matters in dict, not in compare."""
    if len(a) != 6 or len(b) != 6:
        return False
    return a == b


class NvsWhitelist:
    """Mock NVS-backed whitelist, matching the C++ API surface."""

    def __init__(self):
        # List (not set) to preserve insertion order, matching C++ NVS behavior.
        self._macs = []

    def add(self, mac: bytes) -> bool:
        """Add a MAC to the whitelist. Returns True on success.

        C++ behavior:
          - If already present: returns ESP_OK (no-op, no error).
          - If at capacity (4): returns ESP_ERR_NO_MEM.
          - Otherwise: appends and returns ESP_OK.
        """
        if not isinstance(mac, (bytes, bytearray)) or len(mac) != 6:
            return False
        mac = bytes(mac)
        for existing in self._macs:
            if mac_equal(existing, mac):
                return True  # already there, no-op
        if len(self._macs) >= BLE_MAX_PAIRED_CONTROLLERS:
            return False  # at capacity
        self._macs.append(mac)
        return True

    def remove(self, mac: bytes) -> bool:
        """Remove a MAC from the whitelist. Returns True if removed, False if not present.

        C++ behavior: shifts remaining entries down to fill the gap (since
        NVS is blob-based, not contiguous). Python list.pop() does the same.
        """
        if not isinstance(mac, (bytes, bytearray)) or len(mac) != 6:
            return False
        mac = bytes(mac)
        for i, existing in enumerate(self._macs):
            if mac_equal(existing, mac):
                self._macs.pop(i)
                return True
        return False

    def clear(self) -> None:
        """Empty the whitelist."""
        self._macs = []

    def is_whitelisted(self, mac: bytes) -> bool:
        """True if MAC is in the whitelist."""
        if not isinstance(mac, (bytes, bytearray)) or len(mac) != 6:
            return False
        mac = bytes(mac)
        for existing in self._macs:
            if mac_equal(existing, mac):
                return True
        return False

    def count(self) -> int:
        return len(self._macs)

    def get_all(self) -> list:
        """Return a copy of the whitelist in insertion order."""
        return list(self._macs)