// ble_gamepad.h — NimBLE-based standard Bluetooth HID gamepad parser
//
// Replaces Bluepad32 for the single use case of connecting to ONE
// standard BLE HID gamepad (8BitDo, etc.) and exposing its state as
// the same ControllerState struct that myrobot/TaskManager already
// expects.
//
// Design notes:
//   * We do NOT use Bluepad32 or BTstack. NimBLE host only.
//   * We only support the standard HID gamepad report descriptor
//     (the one used by 8BitDo, Gamesir, ipega, etc. in BLE mode).
//     Proprietary controllers (Xbox One, PS5 DualSense, Switch Pro)
//     need a different parser and are out of scope.
//   * Axes are remapped from HID 0..255 / center 127 to BP32-style
//     -512..511 / center 0 so processButtons() / TaskManager need
//     no changes.
//   * Pairing is whitelist-based: up to MAX_PAIRED_CONTROLLERS MACs
//     stored in NVS. First connection auto-locks. Web UI / button
//     can clear whitelist and re-enter pairing.
//
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

// ControllerState is defined in myrobot/Constants.h (v1.3 compat).
// We do NOT redefine it here to avoid ODR violations.
// The v1.3 struct already has the fields we need: leftStickX/Y,
// rightStickX/Y, leftTrigger, rightTrigger, buttons, dpad.
// Connection status is exposed via ble_gamepad_is_connected() instead
// of a struct field (since the v1.3 struct can't be modified from
// this header).
#include "Constants.h"  // for ControllerState

#ifdef __cplusplus
extern "C" {
#endif

// Pairing mode state machine. Visible to web UI / button handlers
// so they can drive transitions cleanly.
typedef enum {
    PAIRING_STATE_IDLE     = 0,  // running, locked to first controller
    PAIRING_STATE_ACCEPT   = 1,  // actively accepting new controllers
    PAIRING_STATE_DISABLED = 2,  // BLE subsystem not started (e.g. WiFi-only mode)
} PairingState;

// Compile-time maximum number of paired controllers we can store.
// This is the size of the NVS-backed whitelist array; raising it means
// increasing flash usage for the storage and the in-RAM cache. Runtime
// policy (how many of these slots are actually *used*) lives in
// output_config's `max_paired` setting and is read by
// ble_gamepad_set_max_paired() at boot.
//
// Kevin's stated default model: one paired controller at a time until
// the user pairs a new one. Pairing a new MAC evicts the existing one
// (see ble_gamepad_add_paired_mac() in the .cpp for the overwrite
// semantics). If you ever need multi-controller (tournament handoff,
// spare controller in the pit), bump this and the runtime cap can go
// up to BLE_MAX_PAIRED_CONTROLLERS.
#define BLE_MAX_PAIRED_CONTROLLERS 4

// Default cap if the NVS-stored value is missing or invalid. Matches
// Kevin's "one controller at a time" preference.
#define BLE_RUNTIME_MAX_PAIRED_DEFAULT  1

// Upper bound on the user-configurable cap; cannot exceed the
// compile-time array size above.
#define BLE_RUNTIME_MAX_PAIRED_CAP      BLE_MAX_PAIRED_CONTROLLERS

// 6-byte MAC address. Big-endian on the wire (Bluetooth standard),
// stored as-is in NVS.
typedef struct {
    uint8_t addr[6];
} ble_mac_t;

// Public API ----------------------------------------------------------------

// Initialize the BLE stack, register GATT/ADV handlers, start scanning.
// Returns ESP_OK on success.
esp_err_t ble_gamepad_init(void);

// Start the NimBLE host task. Call once after init().
// Returns ESP_OK on success.
esp_err_t ble_gamepad_start(void);

// Service finite BLE scan slices while in pairing mode. Call from loop().
void ble_gamepad_poll(void);

// Deinit. Used for OTA reset, factory reset, etc.
void ble_gamepad_deinit(void);

// Get the most recent gamepad state. Safe to call from any task.
// Returns a copy — the internal state is updated by the NimBLE task.
// Note: written as `struct ControllerState` for C compatibility —
// in C++ this is equivalent to the bare `ControllerState` name.
struct ControllerState ble_gamepad_get_state(void);

// Is a controller currently connected and providing reports?
bool ble_gamepad_is_connected(void);

// Copy the currently connected controller MAC into out.
// Returns false when no controller is connected or out is NULL.
bool ble_gamepad_get_connected_mac(ble_mac_t *out);

// Pairing state machine -----------------------------------------------------

// Get current pairing state.
PairingState ble_gamepad_get_pairing_state(void);

// Set pairing state. PairingState::PAIRING_STATE_ACCEPT starts scanning
// and accepts any compatible controller for BLE_PAIRING_WINDOW_MS.
// Returns ESP_OK on success.
esp_err_t ble_gamepad_set_pairing_state(PairingState state);

// Get the list of paired MAC addresses (up to *count).
// out_macs must point to at least BLE_MAX_PAIRED_CONTROLLERS slots.
// *count is set to the number actually written.
void ble_gamepad_get_paired_macs(ble_mac_t *out_macs, uint8_t *count);

// Clear the whitelist. If currently connected, also disconnects.
// After this, pairing state becomes ACCEPT so a new controller can join.
esp_err_t ble_gamepad_clear_paired_macs(void);

// Add a MAC to the whitelist manually (e.g. via web UI).
// If currently connected, does NOT disconnect — the new MAC will be
// allowed next time it appears.
esp_err_t ble_gamepad_add_paired_mac(const ble_mac_t *mac);

// Remove a MAC from the whitelist.
esp_err_t ble_gamepad_remove_paired_mac(const ble_mac_t *mac);

// Disconnect the currently connected controller if any.
// Useful for "force re-pair" flows.
esp_err_t ble_gamepad_disconnect(void);

// Get the current runtime cap (number of whitelist slots actually used).
// Always in [1, BLE_RUNTIME_MAX_PAIRED_CAP]. Defaults to
// BLE_RUNTIME_MAX_PAIRED_DEFAULT until ble_gamepad_set_max_paired()
// is called (typically once after output_config_init()).
uint8_t ble_gamepad_get_max_paired(void);

// Set the runtime cap. n must be in [1, BLE_RUNTIME_MAX_PAIRED_CAP]
// (returns ESP_ERR_INVALID_ARG otherwise). If the stored whitelist is
// longer than n, the oldest slots (highest indices) are evicted
// immediately; the currently-connected controller is NOT disconnected,
// so a connected controller at slot 0 survives a cap reduction.
// Returns ESP_OK on success, ESP_ERR_INVALID_ARG on out-of-range n.
esp_err_t ble_gamepad_set_max_paired(uint8_t n);

#ifdef __cplusplus
}  // extern "C"
#endif

// Callbacks -----------------------------------------------------------------

// Called whenever the connection state changes. web_config uses this
// to update the LED status indicator and broadcast to the web UI.
//
// Note: kept outside the `extern "C"` block on purpose — function-pointer
// types are layout-compatible across C and C++, so consumers can assign
// a C++ lambda or static C function interchangeably.
typedef void (*ble_connection_callback_t)(bool connected, const ble_mac_t *mac);
void ble_gamepad_set_connection_callback(ble_connection_callback_t cb);

// Called whenever the pairing state machine transitions (IDLE <-> ACCEPT,
// or back to IDLE on connect/timeout). The LED1 driver in sketch.cpp uses
// this to blink the debug LED while accepting new controllers. The state
// argument is the new state.
typedef void (*ble_pairing_callback_t)(PairingState state);
void ble_gamepad_set_pairing_callback(ble_pairing_callback_t cb);

#ifdef __cplusplus
extern "C" {
#endif

#ifdef BENCH_HID_PUBLIC
esp_err_t ble_gamepad_bench_set_enabled(bool enabled);
bool ble_gamepad_bench_is_enabled(void);
esp_err_t ble_gamepad_bench_inject_hid_report(const uint8_t *data, uint16_t len);
#else
static inline esp_err_t ble_gamepad_bench_set_enabled(bool) { return ESP_ERR_NOT_SUPPORTED; }
static inline bool ble_gamepad_bench_is_enabled(void) { return false; }
static inline esp_err_t ble_gamepad_bench_inject_hid_report(const uint8_t *, uint16_t) { return ESP_ERR_NOT_SUPPORTED; }
#endif

#ifdef __cplusplus
}  // extern "C"
#endif
