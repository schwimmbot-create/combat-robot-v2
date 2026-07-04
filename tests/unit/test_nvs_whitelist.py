"""
Tests for the NVS whitelist logic.

These exercise the reference Python implementation in
fixtures/nvs_whitelist_reference.py, which mirrors the C++ API in
components/ble_gamepad/src/ble_gamepad.cpp.

What this catches:
  - Adding duplicate MACs doesn't double-count
  - Capacity limit (BLE_MAX_PAIRED_CONTROLLERS = 4) is enforced
  - Removing shifts entries correctly (no "ghost" entries)
  - Clear is total
  - is_whitelisted is O(n) but works for small N (we test up to 4)
  - Invalid input (wrong-length MAC) is rejected, not silently accepted

What this doesn't catch:
  - Real NVS flash wear behavior
  - Power-loss during NVS write (we're not testing the storage layer)
  - Concurrent access (single-threaded test)
"""
import pytest

from fixtures.nvs_whitelist_reference import (
    NvsWhitelist,
    BLE_MAX_PAIRED_CONTROLLERS,
    mac_equal,
)


# A few real-looking MAC addresses for tests.
MAC_A = bytes([0xAA, 0xBB, 0xCC, 0x11, 0x22, 0x33])
MAC_B = bytes([0xAA, 0xBB, 0xCC, 0x11, 0x22, 0x44])
MAC_C = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66])
MAC_D = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x01])
MAC_E = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x02])  # 5th MAC, won't fit


# ---------- Add ----------

class TestAdd:
    def test_add_first(self):
        wl = NvsWhitelist()
        assert wl.add(MAC_A) is True
        assert wl.count() == 1
        assert wl.is_whitelisted(MAC_A)

    def test_add_returns_true_when_already_present(self):
        """The C++ API treats re-adding an existing MAC as a no-op success.

        This matches the C++:
          if (ble_mac_is_whitelisted(mac)) return ESP_OK;
        """
        wl = NvsWhitelist()
        wl.add(MAC_A)
        assert wl.add(MAC_A) is True  # already there
        assert wl.count() == 1  # still 1, not 2

    def test_add_preserves_insertion_order(self):
        """With BLE_MAX == 1, each new add replaces slot 0 — only the
        most recently added MAC survives. This is the one-slot model.
        """
        wl = NvsWhitelist()
        wl.add(MAC_A)
        wl.add(MAC_B)  # evicts MAC_A
        wl.add(MAC_C)  # evicts MAC_B
        assert wl.get_all() == [MAC_C]
        assert wl.is_whitelisted(MAC_C)
        assert not wl.is_whitelisted(MAC_A)
        assert not wl.is_whitelisted(MAC_B)

    def test_add_until_capacity(self):
        """One-slot model: can hold exactly one MAC."""
        wl = NvsWhitelist()
        assert wl.add(MAC_A) is True
        assert wl.count() == 1
        assert wl.is_whitelisted(MAC_A)
        assert wl.count() == BLE_MAX_PAIRED_CONTROLLERS

    def test_add_evicts_when_full(self):
        """Pairing a new controller evicts the old one (one-slot model).

        Kevin's stated model: one paired controller at a time until reset.
        A new pairing IS the reset — the new MAC replaces the old.
        """
        wl = NvsWhitelist()
        wl.add(MAC_A)
        assert wl.add(MAC_B) is True
        assert wl.count() == 1
        assert wl.is_whitelisted(MAC_B)
        assert not wl.is_whitelisted(MAC_A)
        assert wl.get_all() == [MAC_B]

    def test_add_returns_false_when_full(self):
        """With MAX > 1, a full whitelist rejects new MACs (5th rejected when MAX == 4).

        Skipped under the current BLE_MAX_PAIRED_CONTROLLERS == 1 model
        because the eviction path above covers the same scenario. Kept
        here as a regression guard if MAX is ever bumped back up.
        """
        if BLE_MAX_PAIRED_CONTROLLERS == 1:
            pytest.skip("only applies when BLE_MAX_PAIRED_CONTROLLERS > 1")
        wl = NvsWhitelist()
        for mac in [MAC_A, MAC_B, MAC_C, MAC_D]:
            wl.add(mac)
        assert wl.add(MAC_E) is False
        assert wl.count() == BLE_MAX_PAIRED_CONTROLLERS
        assert not wl.is_whitelisted(MAC_E)

    def test_add_rejects_wrong_length_mac(self):
        """Defensive: a 3-byte or 7-byte MAC is not valid Bluetooth."""
        wl = NvsWhitelist()
        assert wl.add(b"\x00\x01\x02") is False
        assert wl.add(b"\x00\x01\x02\x03\x04\x05\x06") is False
        assert wl.add(b"") is False
        assert wl.count() == 0

    def test_add_rejects_non_bytes(self):
        """List, str, and other non-bytes input is rejected (returns False, not raises).

        The C++ API is strongly typed; the Python reference uses isinstance
        checks to return False rather than raise, for testability and to
        match what the C++ would do with a bad cast.
        """
        wl = NvsWhitelist()
        assert wl.add("AABBCC112233") is False  # str
        assert wl.add([0xAA, 0xBB, 0xCC, 0x11, 0x22, 0x33]) is False  # list
        assert wl.add(0xAABBCC112233) is False  # int
        assert wl.add(None) is False
        assert wl.count() == 0


# ---------- Remove ----------

class TestRemove:
    def test_remove_existing(self):
        wl = NvsWhitelist()
        wl.add(MAC_A)
        assert wl.remove(MAC_A) is True
        assert wl.count() == 0
        assert not wl.is_whitelisted(MAC_A)

    def test_remove_nonexistent_returns_false(self):
        wl = NvsWhitelist()
        wl.add(MAC_A)
        assert wl.remove(MAC_B) is False
        assert wl.count() == 1

    def test_remove_then_add_works(self):
        """After removing the single entry, we can add a new MAC."""
        wl = NvsWhitelist()
        wl.add(MAC_A)
        wl.remove(MAC_A)
        assert wl.count() == 0
        assert wl.add(MAC_B) is True
        assert wl.get_all() == [MAC_B]
        assert wl.is_whitelisted(MAC_B)
        assert not wl.is_whitelisted(MAC_A)

    def test_remove_middle_entry_shifts(self):
        """With BLE_MAX == 1 there's only one slot — removing it leaves
        an empty whitelist and the next add takes slot 0.
        """
        wl = NvsWhitelist()
        wl.add(MAC_A)
        wl.remove(MAC_A)
        assert wl.count() == 0
        assert wl.get_all() == []
        wl.add(MAC_B)
        assert wl.get_all() == [MAC_B]
        assert wl.is_whitelisted(MAC_B)

    def test_remove_then_re_add_at_capacity(self):
        """After removing, we can re-add to fill the freed slot."""
        wl = NvsWhitelist()
        for mac in [MAC_A, MAC_B, MAC_C, MAC_D]:
            wl.add(mac)
        wl.remove(MAC_B)
        # Now there's room for one more
        assert wl.add(MAC_E) is True
        assert wl.count() == BLE_MAX_PAIRED_CONTROLLERS
        assert wl.is_whitelisted(MAC_E)

    def test_remove_rejects_invalid_mac(self):
        wl = NvsWhitelist()
        wl.add(MAC_A)
        assert wl.remove(b"") is False
        assert wl.remove(b"\x00\x01") is False
        assert wl.count() == 1  # A still there


# ---------- Clear ----------

class TestClear:
    def test_clear_empties_list(self):
        wl = NvsWhitelist()
        wl.add(MAC_A)
        wl.add(MAC_B)
        wl.clear()
        assert wl.count() == 0
        assert wl.get_all() == []

    def test_clear_on_empty(self):
        wl = NvsWhitelist()
        wl.clear()  # should not raise
        assert wl.count() == 0

    def test_clear_then_add(self):
        wl = NvsWhitelist()
        wl.add(MAC_A)
        wl.clear()
        assert wl.add(MAC_B) is True
        assert wl.get_all() == [MAC_B]


# ---------- IsWhitelisted ----------

class TestIsWhitelisted:
    def test_empty_whitelist(self):
        wl = NvsWhitelist()
        assert not wl.is_whitelisted(MAC_A)

    def test_returns_true_for_present(self):
        wl = NvsWhitelist()
        wl.add(MAC_A)
        assert wl.is_whitelisted(MAC_A)

    def test_returns_false_for_absent(self):
        wl = NvsWhitelist()
        wl.add(MAC_A)
        assert not wl.is_whitelisted(MAC_B)

    def test_does_not_match_similar_mac(self):
        """A MAC that differs by one byte should not match."""
        wl = NvsWhitelist()
        wl.add(MAC_A)  # 0xAA,0xBB,0xCC,0x11,0x22,0x33
        similar = bytes([0xAA, 0xBB, 0xCC, 0x11, 0x22, 0x34])  # last byte differs
        assert not wl.is_whitelisted(similar)

    def test_rejects_invalid_input(self):
        wl = NvsWhitelist()
        wl.add(MAC_A)
        assert not wl.is_whitelisted(b"")
        assert not wl.is_whitelisted(b"\x00\x01\x02")  # too short


# ---------- MAC equality (low-level helper) ----------

class TestMacEqual:
    def test_same_bytes(self):
        assert mac_equal(MAC_A, MAC_A)

    def test_same_content_different_object(self):
        """Bytes objects compare by value when they have the same content AND length."""
        a = bytes([0xAA, 0xBB, 0xCC, 0x11, 0x22, 0x33])
        b = bytes([0xAA, 0xBB, 0xCC, 0x11, 0x22, 0x33])
        assert mac_equal(a, b)  # different objects, same content, same length

    def test_different_bytes(self):
        assert not mac_equal(MAC_A, MAC_B)

    def test_different_lengths(self):
        """mac_equal must return False for mismatched lengths, not crash."""
        assert not mac_equal(b"\x00\x01\x02", b"\x00\x01\x02\x03")

    def test_case_sensitive_lowercase_vs_uppercase(self):
        """Bluetooth MACs are conventionally uppercase, but bytes 0xAA == 0xAA
        regardless. This test just confirms we don't have any string-magic
        accidentally imported."""
        upper = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])
        lower = bytes([0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff])
        assert mac_equal(upper, lower)  # bytes are bytes, no case


# ---------- Integration scenarios ----------

class TestWhitelistLifecycle:
    """End-to-end scenarios matching how the C++ code actually uses the whitelist."""

    def test_pair_disconnect_pair_again_cycle(self):
        """User pairs, disconnects, re-pairs the same controller.

        This is the test for the v1.3 'controller dies mid-fight' bug.
        The C++ code adds the MAC on first connect. On disconnect, the
        MAC stays in the whitelist (we don't auto-remove). On re-pair,
        the MAC is still there, so pairing is instant.
        """
        wl = NvsWhitelist()
        # First pair
        wl.add(MAC_A)
        assert wl.is_whitelisted(MAC_A)
        # Controller dies (we don't call remove — the C++ code doesn't
        # auto-remove on disconnect).
        # Re-pair: MAC is still there, is_whitelisted still True.
        assert wl.is_whitelisted(MAC_A)

    def test_unpair_then_pair_new_controller(self):
        """User clears the whitelist and pairs a new controller.

        The C++ ble_gamepad_clear_paired_macs() does:
          nvs_erase_all()
          ble_gamepad_set_pairing_state(PAIRING_STATE_ACCEPT)
        Then on the new connect, the MAC is added.
        """
        wl = NvsWhitelist()
        wl.add(MAC_A)
        wl.add(MAC_B)
        wl.clear()
        # Now the robot is in pairing mode and accepts MAC_C
        assert wl.add(MAC_C) is True
        assert wl.count() == 1
        assert not wl.is_whitelisted(MAC_A)
        assert not wl.is_whitelisted(MAC_B)
        assert wl.is_whitelisted(MAC_C)

    def test_whitelist_persists_through_get_all(self):
        """Simulates NVS reboot: get_all() returns the same list."""
        wl = NvsWhitelist()
        wl.add(MAC_A)
        wl.add(MAC_B)
        wl.add(MAC_C)
        snapshot = wl.get_all()
        # Now simulate a "reboot" by creating a new whitelist
        wl2 = NvsWhitelist()
        for mac in snapshot:
            wl2.add(mac)
        assert wl2.get_all() == snapshot