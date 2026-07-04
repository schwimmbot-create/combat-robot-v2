"""
Reference Python implementation of the NVS whitelist logic.

The C++ code in components/ble_gamepad/src/ble_gamepad.cpp implements
this against the real NVS flash storage. This file replicates the
SAME behavior in Python using a list-based mock, so the unit tests
can exercise the logic without flashing firmware.

API surface (must match ble_gamepad.h public API):
  - add(mac)            -> True if added (or evictee), False otherwise
  - remove(mac)         -> True if removed, False if not present
  - clear()             -> empties the whitelist
  - is_whitelisted(mac) -> bool
  - count()             -> number of stored MACs
  - get_all()           -> list of stored MACs (in slot order)
  - get_max_paired()    -> current runtime cap
  - set_max_paired(n)   -> set runtime cap; evicts excess on shrink

Compile-time array cap (BLE_MAX_PAIRED_CONTROLLERS): 4 (mirror of
ble_gamepad.h). Runtime cap defaults to 1 (BLE_RUNTIME_MAX_PAIRED_DEFAULT)
and is user-configurable via the web UI (ble_gamepad_set_max_paired).

Kevin's stated default model: one paired controller at a time. Pairing
a new MAC beyond the cap evicts the oldest (LIFO) - slot 0 is dropped,
slot N-1 is overwritten with the new MAC.

See: components/ble_gamepad/src/ble_gamepad.cpp::nvs_*_mac and
     components/ble_gamepad/src/ble_gamepad.cpp::ble_gamepad_*_mac
"""

# Must match components/ble_gamepad/include/ble_gamepad.h
BLE_MAX_PAIRED_CONTROLLERS = 4
BLE_RUNTIME_MAX_PAIRED_DEFAULT = 1
BLE_RUNTIME_MAX_PAIRED_CAP = BLE_MAX_PAIRED_CONTROLLERS


def mac_equal(a: bytes, b: bytes) -> bool:
    """Compare two 6-byte MAC addresses."""
    if len(a) != 6 or len(b) != 6:
        return False
    return a == b


class NvsWhitelist:
    """Mock NVS-backed whitelist with runtime cap, matching the C++ API."""

    def __init__(self, max_paired: int = BLE_RUNTIME_MAX_PAIRED_DEFAULT):
        # List to preserve slot order, matching C++ NVS blob layout.
        self._macs = []
        self._max_paired = max_paired

    def get_max_paired(self) -> int:
        return self._max_paired

    def set_max_paired(self, n: int) -> bool:
        """Set runtime cap. Returns True on success, False if out of [1, CAP]."""
        if n < 1 or n > BLE_RUNTIME_MAX_PAIRED_CAP:
            return False
        old = self._max_paired
        self._max_paired = n
        if n < old:
            # Evict the excess (highest-index slots) so the stored
            # count never exceeds the policy.
            if len(self._macs) > n:
                self._macs = self._macs[:n]
        return True

    def add(self, mac: bytes) -> bool:
        """Add a MAC to the whitelist. Returns True on success.

        C++ behavior:
          - If already present: returns ESP_OK (no-op, no error).
          - If at runtime capacity: LIFO eviction - shift older
            entries toward slot 0, write new MAC at the highest slot.
        """
        if not isinstance(mac, (bytes, bytearray)) or len(mac) != 6:
            return False
        mac = bytes(mac)
        for existing in self._macs:
            if mac_equal(existing, mac):
                return True  # already there, no-op
        if len(self._macs) >= self._max_paired:
            # LIFO eviction: shift slot[i] = slot[i+1] for i in [0..cap-2),
            # then write new MAC at slot[cap-1].
            for i in range(self._max_paired - 1):
                if i + 1 < len(self._macs):
                    self._macs[i] = self._macs[i + 1]
                else:
                    break
            if len(self._macs) < self._max_paired:
                self._macs.append(mac)
            else:
                self._macs[self._max_paired - 1] = mac
            return True
        self._macs.append(mac)
        return True

    def remove(self, mac: bytes) -> bool:
        """Remove a MAC from the whitelist (shifts entries down)."""
        if not isinstance(mac, (bytes, bytearray)) or len(mac) != 6:
            return False
        mac = bytes(mac)
        for i, existing in enumerate(self._macs):
            if mac_equal(existing, mac):
                self._macs.pop(i)
                return True
        return False

    def clear(self) -> None:
        self._macs = []

    def is_whitelisted(self, mac: bytes) -> bool:
        if not isinstance(mac, (bytes, bytearray)) or len(mac) != 6:
            return False
        mac = bytes(mac)
        return any(mac_equal(existing, mac) for existing in self._macs)

    def count(self) -> int:
        return len(self._macs)

    def get_all(self) -> list:
        return list(self._macs)
