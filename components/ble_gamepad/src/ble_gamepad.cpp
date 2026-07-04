// ble_gamepad.cpp — NimBLE-Arduino standard Bluetooth HID gamepad parser
//
// Replaces Bluepad32 for a single BLE HID gamepad (8BitDo etc.) while
// staying in PlatformIO's framework=arduino build mode. Do not include
// raw ESP-IDF NimBLE headers here; those require fragile manual libbt
// linkage under PlatformIO and hit toolchain/ABI mismatches on ESP32-C3.
//
// SPDX-License-Identifier: Apache-2.0

#include "ble_gamepad.h"

#include <string.h>

#include <Arduino.h>
#include <NimBLEDevice.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "freertos/portmacro.h"  // portENTER_CRITICAL / portEXIT_CRITICAL

static const char *TAG = "ble_gamepad";

#define BLE_SERIALF(...) do { \
    if (Serial) { \
        Serial.printf(__VA_ARGS__); \
    } \
} while (0)

static const NimBLEUUID UUID_HID((uint16_t)0x1812);
static const NimBLEUUID UUID_CHR_REPORT((uint16_t)0x2a4d);
static const NimBLEUUID UUID_CHR_REPORT_MAP((uint16_t)0x2a4b);
static const NimBLEUUID UUID_CHR_PROTOCOL_MODE((uint16_t)0x2a4e);
static const NimBLEUUID UUID_DSC_REPORT_REF((uint16_t)0x2908);
static const NimBLEUUID UUID_BENCH_SERVICE("7d2f0001-0f3a-4b8a-9b7d-2f4c9a000001");
static const NimBLEUUID UUID_BENCH_HID_WRITE("7d2f0002-0f3a-4b8a-9b7d-2f4c9a000001");

#define NVS_NAMESPACE       "ble_paired"
#define NVS_KEY_COUNT       "count"
#define NVS_KEY_MAC_FMT     "mac_%d"
#define BLE_PAIRING_WINDOW_MS 60000

static void start_scan(void);
static void stop_scan(void);
static void scan_complete_cb(NimBLEScanResults results);
static void parse_hid_report(const uint8_t *data, uint16_t len);
static void notify_connection_change(bool connected, const ble_mac_t *mac);

static uint32_t s_last_scan_attempt_ms = 0;
static uint32_t s_last_scan_complete_ms = 0;

static struct {
    PairingState pairing_state;
    ControllerState controller_state;
    // Spinlock protecting controller_state against torn reads between
    // the NimBLE task (write side, in parse_*_hid_report) and the
    // Arduino loop (read side, in ble_gamepad_get_state). Held for the
    // duration of a single ControllerState write or copy — never across
    // any blocking or allocation call.
    portMUX_TYPE lock;
    bool connected;
    ble_mac_t connected_mac;
    ble_connection_callback_t connection_cb;
    esp_timer_handle_t pairing_timer;
    NimBLEClient *client;
    NimBLEServer *bench_server;
    NimBLECharacteristic *bench_write_char;
    NimBLEAdvertisedDevice target;
    bool have_target;
    bool scan_active;
    bool auto_reconnect;
} s_state = {
    .pairing_state = PAIRING_STATE_IDLE,
    .lock = portMUX_INITIALIZER_UNLOCKED,
    .connected = false,
    .connection_cb = NULL,
    .pairing_timer = NULL,
    .client = NULL,
    .bench_server = NULL,
    .bench_write_char = NULL,
    .have_target = false,
    .scan_active = false,
    .auto_reconnect = false,
};

// --- Bench HID injection helpers (gated by BENCH_HID_PUBLIC build flag) ---

#define BLE_BENCH_FLAG_NAMESPACE     "bench"
#define BLE_BENCH_FLAG_KEY_ENABLED   "hid_enabled"

#ifdef BENCH_HID_PUBLIC
bool ble_gamepad_bench_is_enabled(void) {
    nvs_handle_t h;
    if (nvs_open(BLE_BENCH_FLAG_NAMESPACE, NVS_READONLY, &h) != ESP_OK) return false;
    uint8_t v = 0;
    esp_err_t err = nvs_get_u8(h, BLE_BENCH_FLAG_KEY_ENABLED, &v);
    nvs_close(h);
    return (err == ESP_OK && v != 0);
}

esp_err_t ble_gamepad_bench_set_enabled(bool enabled) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(BLE_BENCH_FLAG_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    err = nvs_set_u8(h, BLE_BENCH_FLAG_KEY_ENABLED, enabled ? 1 : 0);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}

esp_err_t ble_gamepad_bench_inject_hid_report(const uint8_t *data, uint16_t len) {
    if (!ble_gamepad_bench_is_enabled()) return ESP_ERR_INVALID_STATE;
    if (data == nullptr || len == 0) return ESP_ERR_INVALID_ARG;
    parse_hid_report(data, len);

    static const ble_mac_t bench_mac = {{0x02, 0x00, 0x00, 0x00, 0xbe, 0x7c}};
    s_state.connected_mac = bench_mac;
    if (!s_state.connected) notify_connection_change(true, &s_state.connected_mac);
    ESP_LOGD(TAG, "bench HID frame accepted (%u bytes)", (unsigned)len);
    return ESP_OK;
}
#endif  // BENCH_HID_PUBLIC

// --- NVS whitelist helpers ----------------------------------------------

static esp_err_t nvs_read_mac(int idx, ble_mac_t *out) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &h);
    if (err != ESP_OK) return err;
    char key[16];
    snprintf(key, sizeof(key), NVS_KEY_MAC_FMT, idx);
    size_t sz = sizeof(*out);
    err = nvs_get_blob(h, key, out, &sz);
    nvs_close(h);
    return err;
}

static esp_err_t nvs_write_mac(int idx, const ble_mac_t *mac) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    char key[16];
    snprintf(key, sizeof(key), NVS_KEY_MAC_FMT, idx);
    err = nvs_set_blob(h, key, mac, sizeof(*mac));
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}

static esp_err_t nvs_clear_all_macs(void) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    err = nvs_erase_all(h);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}

static uint8_t nvs_get_count(void) {
    nvs_handle_t h;
    uint8_t count = 0;
    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) != ESP_OK) return 0;
    nvs_get_u8(h, NVS_KEY_COUNT, &count);
    nvs_close(h);
    return count;
}

static esp_err_t nvs_set_count(uint8_t count) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    err = nvs_set_u8(h, NVS_KEY_COUNT, count);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}

static void address_to_mac(const NimBLEAddress &address, ble_mac_t *out) {
    const uint8_t *native = address.getNative();
    memcpy(out->addr, native, sizeof(out->addr));
}

static bool ble_mac_equal(const ble_mac_t *a, const ble_mac_t *b) {
    return memcmp(a->addr, b->addr, 6) == 0;
}

static bool ble_mac_is_whitelisted(const ble_mac_t *mac) {
    uint8_t count = nvs_get_count();
    for (int i = 0; i < count; i++) {
        ble_mac_t stored;
        if (nvs_read_mac(i, &stored) == ESP_OK && ble_mac_equal(&stored, mac)) {
            return true;
        }
    }
    return false;
}

void ble_gamepad_get_paired_macs(ble_mac_t *out_macs, uint8_t *count) {
    uint8_t n = nvs_get_count();
    if (n > BLE_MAX_PAIRED_CONTROLLERS) n = BLE_MAX_PAIRED_CONTROLLERS;
    for (int i = 0; i < n; i++) {
        if (nvs_read_mac(i, &out_macs[i]) != ESP_OK) {
            *count = i;
            return;
        }
    }
    *count = n;
}

esp_err_t ble_gamepad_add_paired_mac(const ble_mac_t *mac) {
    if (ble_mac_is_whitelisted(mac)) return ESP_OK;
    uint8_t count = nvs_get_count();
    if (count >= BLE_MAX_PAIRED_CONTROLLERS) {
        // One-slot model (BLE_MAX_PAIRED_CONTROLLERS == 1): evict the
        // existing entry so a freshly paired controller can take its
        // place. With MAX > 1, we'd reject here with ESP_ERR_NO_MEM, but
        // for MAX == 1 "pair a new controller" is the user's reset, so
        // overwriting slot 0 is the intended behavior.
        if (BLE_MAX_PAIRED_CONTROLLERS == 1) {
            esp_err_t err = nvs_write_mac(0, mac);
            if (err != ESP_OK) return err;
            return nvs_set_count(1);
        }
        return ESP_ERR_NO_MEM;
    }
    esp_err_t err = nvs_write_mac(count, mac);
    if (err != ESP_OK) return err;
    return nvs_set_count(count + 1);
}

esp_err_t ble_gamepad_remove_paired_mac(const ble_mac_t *mac) {
    uint8_t count = nvs_get_count();
    int match_idx = -1;
    for (int i = 0; i < count; i++) {
        ble_mac_t stored;
        if (nvs_read_mac(i, &stored) == ESP_OK && ble_mac_equal(&stored, mac)) {
            match_idx = i;
            break;
        }
    }
    if (match_idx < 0) return ESP_ERR_NOT_FOUND;
    for (int i = match_idx; i < count - 1; i++) {
        ble_mac_t next;
        if (nvs_read_mac(i + 1, &next) == ESP_OK) nvs_write_mac(i, &next);
    }
    return nvs_set_count(count - 1);
}

// --- HID report parsing --------------------------------------------------

static int scale_axis_full(uint8_t v) {
    return ((int)v - 127) * 4;
}

static uint16_t decode_hat(uint8_t hat) {
    switch (hat) {
        case 0: return 0x01;              // up
        case 1: return 0x01 | 0x08;       // up + right
        case 2: return 0x08;              // right
        case 3: return 0x02 | 0x08;       // down + right
        case 4: return 0x02;              // down
        case 5: return 0x02 | 0x04;       // down + left
        case 6: return 0x04;              // left
        case 7: return 0x01 | 0x04;       // up + left
        default: return 0;
    }
}

static uint16_t decode_8bitdo_buttons(uint8_t b0, uint8_t b1) {
    uint16_t buttons = 0;
    if (b0 & 0x01) buttons |= (1u << 0);  // A
    if (b0 & 0x02) buttons |= (1u << 1);  // B
    if (b0 & 0x08) buttons |= (1u << 2);  // X
    if (b0 & 0x10) buttons |= (1u << 3);  // Y
    if (b0 & 0x40) buttons |= (1u << 4);  // L1
    if (b0 & 0x80) buttons |= (1u << 5);  // R1
    if (b1 & 0x01) buttons |= (1u << 6);  // L2 digital
    if (b1 & 0x02) buttons |= (1u << 7);  // R2 digital
    if (b1 & 0x04) buttons |= (1u << 8);  // SELECT / SHARE
    if (b1 & 0x08) buttons |= (1u << 9);  // START / OPTIONS
    if (b1 & 0x20) buttons |= (1u << 10); // L3
    if (b1 & 0x40) buttons |= (1u << 11); // R3
    if (b1 & 0x10) buttons |= (1u << 12); // HOME
    return buttons;
}

static void parse_8bitdo_report(const uint8_t *data, uint16_t base) {
    // 8BitDo Ultimate 2 capture via Windows HIDAPI:
    //   report-id?, hat, LX, LY, RX, RY, R2, L2, buttons0, buttons1, ...
    // BLE HOGP may strip the report-id byte, so `base` is the hat offset.
    //
    // The 8 field writes below MUST be atomic vs ble_gamepad_get_state()
    // reads from the Arduino loop. Without this guard, a FreeRTOS tick
    // can preempt mid-write and return a half-old-half-new ControllerState
    // to the motor driver (torn read).
    portENTER_CRITICAL(&s_state.lock);
    s_state.controller_state.leftStickX = scale_axis_full(data[base + 1]);
    s_state.controller_state.leftStickY = scale_axis_full(data[base + 2]);
    s_state.controller_state.rightStickX = scale_axis_full(data[base + 3]);
    s_state.controller_state.rightStickY = scale_axis_full(data[base + 4]);
    s_state.controller_state.rightTrigger = (int)data[base + 5] * 4;
    s_state.controller_state.leftTrigger = (int)data[base + 6] * 4;
    s_state.controller_state.buttons = decode_8bitdo_buttons(data[base + 7], data[base + 8]);
    s_state.controller_state.dpad = decode_hat(data[base]);
    portEXIT_CRITICAL(&s_state.lock);
}

static void parse_standard_hid_report(const uint8_t *data, uint16_t len) {
    if (len < 8) return;
    // Atomic vs ble_gamepad_get_state() — see parse_8bitdo_report().
    portENTER_CRITICAL(&s_state.lock);
    s_state.controller_state.leftStickX = scale_axis_full(data[0]);
    s_state.controller_state.leftStickY = scale_axis_full(data[1]);
    s_state.controller_state.rightStickX = scale_axis_full(data[2]);
    s_state.controller_state.rightStickY = scale_axis_full(data[3]);
    if (len >= 6) s_state.controller_state.buttons = data[4] | (data[5] << 8);
    if (len >= 8) {
        s_state.controller_state.leftTrigger = (int)data[6] * 4;
        s_state.controller_state.rightTrigger = (int)data[7] * 4;
    }
    if (len >= 9) s_state.controller_state.dpad = decode_hat(data[8]);
    portEXIT_CRITICAL(&s_state.lock);
}

static void parse_hid_report(const uint8_t *data, uint16_t len) {
    if (data == nullptr) return;
    // Hard upper bound: parse_8bitdo_report reads up to data[base+8] (9 bytes)
    // and parse_standard_hid_report reads up to data[8] — reject anything
    // shorter than 10 bytes to keep both parsers in-bounds.
    if (len < 10) return;

    // 8BitDo Ultimate 2 over Windows HIDAPI emits 34-byte reports with a
    // leading report-id byte: 01 0f 7f 7f 7f 7f 00 00 00 00 ... .
    // NimBLE's Report characteristic may deliver the same payload without
    // the report-id, so accept both base offsets.
    if (data[0] == 0x01 && data[1] <= 0x0f) {
        parse_8bitdo_report(data, 1);
        return;
    }
    // No report-id prefix: 8BitDo variant begins with 0x0f as a hat/dpad
    // byte, never 0x01. Use len >= 10 (not > 12) — the previous condition
    // silently dropped reports of length 10–12 in this branch.
    if (data[0] <= 0x0f) {
        parse_8bitdo_report(data, 0);
        return;
    }

    parse_standard_hid_report(data, len);
}

// --- NimBLE-Arduino callbacks -------------------------------------------

// bench injection moved to gated helper above

#ifdef BENCH_HID_PUBLIC
class BenchWriteCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic *chr) override {
        std::string value = chr->getValue();
        if (value.empty()) return;
        ble_gamepad_bench_inject_hid_report(
            reinterpret_cast<const uint8_t *>(value.data()), value.size());
    }
};

static BenchWriteCallbacks s_bench_write_callbacks;
#endif  // BENCH_HID_PUBLIC

static void notify_cb(NimBLERemoteCharacteristic *chr, uint8_t *data,
                      size_t len, bool is_notify) {
    (void)chr;
    (void)is_notify;
    parse_hid_report(data, (uint16_t)len);
}

class GamepadClientCallbacks : public NimBLEClientCallbacks {
    void onConnect(NimBLEClient *client) override {
        (void)client;
        BLE_SERIALF("[BLE] onConnect conn_id=%u\r\n", client->getConnId());
    }

    // Reply with a fixed passkey (000000) when the 8BitDo asks.
    // Just-Works over BLE without local IO needs a numeric fallback
    // value to satisfy Security Manager protocol.
    uint32_t onPassKeyRequest() override {
        BLE_SERIALF("[BLE] passkey requested -> 000000\r\n");
        return (uint32_t)0;
    }

    void onDisconnect(NimBLEClient *client) override {
        (void)client;
        ESP_LOGW(TAG, "Controller disconnected");
        s_state.connected = false;
        s_state.client = nullptr;
        // Zero-fill the controller state under the spinlock so a racing
        // ble_gamepad_get_state() can't read a half-cleared struct.
        portENTER_CRITICAL(&s_state.lock);
        s_state.controller_state = ControllerState{};
        portEXIT_CRITICAL(&s_state.lock);
        notify_connection_change(false, &s_state.connected_mac);
        if (s_state.pairing_state == PAIRING_STATE_DISABLED) return;
        // Always allow auto-reconnect if any whitelisted MAC still exists.
        if (nvs_get_count() > 0) s_state.auto_reconnect = true;
        start_scan();
    }
};

static GamepadClientCallbacks s_client_callbacks;

static bool connect_to_target(void) {
    if (!s_state.have_target) return false;

    // Consume the deferred target. If the connection fails, scan restarts and
    // a fresh advertisement will set have_target again. This prevents a stale
    // NimBLEAdvertisedDevice copy from being retried forever.
    s_state.have_target = false;
    stop_scan();
    NimBLEClient *client = NimBLEDevice::createClient();
    if (client == nullptr) return false;
    client->setClientCallbacks(&s_client_callbacks, false);
    // Supervision timeout = 1000 (10 s). The 8BitDo drops the link around the
    // 4-s mark if nothing meaningful has been done with the connection; the
    // wider window gives our warmup Report Map read + characteristic discover
    // + subscribe time to complete before the controller gives up.
    client->setConnectionParams(24, 40, 0, 1000);

    ESP_LOGI(TAG, "Connecting to %s", s_state.target.getAddress().toString().c_str());
    BLE_SERIALF("[BLE] connecting addr=%s\r\n", s_state.target.getAddress().toString().c_str());
    if (!client->connect(&s_state.target)) {
        ESP_LOGW(TAG, "Connect failed");
        BLE_SERIALF("[BLE] connect failed addr=%s\r\n", s_state.target.getAddress().toString().c_str());
        NimBLEDevice::deleteClient(client);
        start_scan();
        return false;
    }

    NimBLERemoteService *hid = client->getService(UUID_HID);
    if (hid == nullptr) {
            ESP_LOGW(TAG, "Connected device has no HID service");
        BLE_SERIALF("[BLE] HID service missing addr=%s\r\n", s_state.target.getAddress().toString().c_str());
        client->disconnect();
        NimBLEDevice::deleteClient(client);
        start_scan();
        return false;
    }

    // Warmup read: HID Report Map (0x2A4B) before notify-subscribe.
    // Real HID hosts do this; without it the 8BitDo can tear down the link
    // shortly after subscribe.
    NimBLERemoteCharacteristic *report_map = hid->getCharacteristic(UUID_CHR_REPORT_MAP);
    if (report_map != nullptr) {
        NimBLEAttValue map_data = report_map->readValue();
        (void)map_data;
    }

    // HID Report characteristics are distinguished by their Report Reference
    // descriptor (0x2908): byte0=report id, byte1=type (1=input, 2=output,
    // 3=feature). The 8BitDo Ultimate 2 exposes at least two notifiable input
    // Report chars; handle 25/id=2 stays quiet while handle 29/id=1 carries
    // gamepad state. Subscribe to every notifiable/indicatable input report.
    int subscribed_reports = 0;
    std::vector<NimBLERemoteCharacteristic *> *chars = hid->getCharacteristics(true);
    if (chars != nullptr) {
        for (NimBLERemoteCharacteristic *chr : *chars) {
            if (chr == nullptr || !(chr->getUUID() == UUID_CHR_REPORT)) continue;
            uint8_t report_type = 0xff;
            NimBLERemoteDescriptor *ref = chr->getDescriptor(UUID_DSC_REPORT_REF);
            if (ref != nullptr) {
                NimBLEAttValue ref_data = ref->readValue();
                if (ref_data.size() >= 2) report_type = ref_data[1];
            }
            if ((report_type == 0xff || report_type == 1) && (chr->canNotify() || chr->canIndicate())) {
                bool use_notify = chr->canNotify();
                BLE_SERIALF("[BLE] subscribing HID input report handle=%u notify=%d type=%u\r\n",
                            chr->getHandle(), (int)use_notify, (unsigned)report_type);
                if (chr->subscribe(use_notify, notify_cb)) subscribed_reports++;
            }
        }
    }

    if (subscribed_reports == 0) {
        ESP_LOGW(TAG, "No HID input report characteristic subscribed");
        BLE_SERIALF("[BLE] no HID input report subscribed\r\n");
        client->disconnect();
        NimBLEDevice::deleteClient(client);
        start_scan();
        return false;
    }

    s_state.client = client;
    s_state.connected = true;
    address_to_mac(s_state.target.getAddress(), &s_state.connected_mac);
    if (!ble_mac_is_whitelisted(&s_state.connected_mac)) {
        ble_gamepad_add_paired_mac(&s_state.connected_mac);
    }
    if (s_state.pairing_timer != NULL) esp_timer_stop(s_state.pairing_timer);
    s_state.pairing_state = PAIRING_STATE_IDLE;
    notify_connection_change(true, &s_state.connected_mac);
    ESP_LOGI(TAG, "Subscribed to HID reports");
    BLE_SERIALF("[BLE] subscribed pairing=locked\r\n");
    return true;
}

static bool is_8bitdo_ultimate_name(NimBLEAdvertisedDevice *device) {
    if (device == nullptr || !device->haveName()) return false;
    std::string name = device->getName();
    return name.find("8BitDo Ultimate") != std::string::npos;
}

class GamepadAdvertisedDeviceCallbacks : public NimBLEAdvertisedDeviceCallbacks {
    void onResult(NimBLEAdvertisedDevice *device) override {
        if (device->haveName()) {
            BLE_SERIALF("[BLE_ADV] %s rssi=%d\r\n", device->getName().c_str(), device->getRSSI());
        } else {
            BLE_SERIALF("[BLE_ADV] %s rssi=%d\r\n", device->getAddress().toString().c_str(), device->getRSSI());
        }
        if (device->isAdvertisingService(UUID_HID)) {
            BLE_SERIALF("[BLE_ADV] HID matches: %s\r\n", device->getAddress().toString().c_str());
        }
        if (!device->isAdvertisingService(UUID_HID)) return;

        ble_mac_t mac;
        address_to_mac(device->getAddress(), &mac);
        bool pairing_open = (s_state.pairing_state == PAIRING_STATE_ACCEPT);
        bool whitelisted = ble_mac_is_whitelisted(&mac);
        bool known_8bitdo_rotation = s_state.auto_reconnect && (nvs_get_count() > 0) &&
                                     is_8bitdo_ultimate_name(device);
        if (!pairing_open && !whitelisted && !known_8bitdo_rotation) {
            return;
        }

        s_state.target = *device;
        s_state.have_target = true;
        BLE_SERIALF("[BLE] target found; deferring connect addr=%s\r\n", device->getAddress().toString().c_str());
        stop_scan();
    }
};

static GamepadAdvertisedDeviceCallbacks s_scan_callbacks;

// --- Scan / connection state ---------------------------------------------

static void notify_connection_change(bool connected, const ble_mac_t *mac) {
    s_state.connected = connected;
    if (s_state.connection_cb) s_state.connection_cb(connected, mac);
}

static void scan_complete_cb(NimBLEScanResults results) {
    (void)results;
    s_state.scan_active = false;
    s_last_scan_complete_ms = millis();
    NimBLEDevice::getScan()->clearResults();
    BLE_SERIALF("[BLE] scan_complete state=%d target=%d\r\n", (int)s_state.pairing_state, (int)s_state.have_target);
}

static void start_scan(void) {
    // Two valid reasons to scan: (1) the user just entered ACCEPT for new
    // pairings; (2) we have a whitelisted controller and want to auto-
    // reconnect when it powers on. Either is enough to start a scan slice.
    bool accept_open = (s_state.pairing_state == PAIRING_STATE_ACCEPT);
    bool auto_open = s_state.auto_reconnect &&
                     (s_state.pairing_state != PAIRING_STATE_DISABLED);
    if (!accept_open && !auto_open) {
        ESP_LOGD(TAG, "start_scan: skipping state=%d auto=%d",
                 (int)s_state.pairing_state, (int)s_state.auto_reconnect);
        return;
    }
    if (s_state.connected || s_state.have_target) {
        ESP_LOGD(TAG, "start_scan: connected=%d target=%d", (int)s_state.connected, (int)s_state.have_target);
        return;
    }

    NimBLEScan *scan = NimBLEDevice::getScan();
    if (scan->isScanning() || s_state.scan_active) {
        s_state.scan_active = true;
        return;
    }

    uint32_t now = millis();
    if (now - s_last_scan_attempt_ms < 1000) return;
    if (s_last_scan_complete_ms != 0 && now - s_last_scan_complete_ms < 250) return;
    s_last_scan_attempt_ms = now;

    scan->clearResults();
    scan->setAdvertisedDeviceCallbacks(&s_scan_callbacks, false);
    scan->setActiveScan(true);
    scan->setInterval(45);
    scan->setWindow(15);

    bool ok = scan->start(/*duration_seconds=*/1, scan_complete_cb, false);
    s_state.scan_active = ok;
    if (!ok) {
        // NimBLE can briefly report busy after stop/complete. Keep retries
        // slow and explicit so we don't starve WiFi or spam the host task.
        scan->stop();
        scan->clearResults();
    }
    ESP_LOGI(TAG, "start_scan: ok=%d state=%d slice=1s", (int)ok, (int)s_state.pairing_state);
    BLE_SERIALF("[BLE] start_scan ok=%d state=%d slice=1s\r\n", (int)ok, (int)s_state.pairing_state);
}

static void stop_scan(void) {
    NimBLEScan *scan = NimBLEDevice::getScan();
    if (scan->isScanning()) scan->stop();
    s_state.scan_active = false;
    scan->clearResults();
}

static void pairing_window_expired_cb(void *arg) {
    (void)arg;
    ESP_LOGW(TAG, "Pairing window expired, locking down");
    s_state.pairing_state = PAIRING_STATE_IDLE;
    stop_scan();
}

// --- Public API -----------------------------------------------------------

esp_err_t ble_gamepad_init(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    if (err != ESP_OK) return err;

    if (s_state.pairing_timer == NULL) {
        const esp_timer_create_args_t timer_args = {
            .callback = &pairing_window_expired_cb,
            .arg = NULL,
            .dispatch_method = ESP_TIMER_TASK,
            .name = "ble_pairing",
            .skip_unhandled_events = true,
        };
        err = esp_timer_create(&timer_args, &s_state.pairing_timer);
        if (err != ESP_OK) return err;
    }

    NimBLEDevice::init("CombatRobot-v2");
    NimBLEDevice::setPower(ESP_PWR_LVL_P9);
    // 8BitDo pairing: SC + bonding, no MITM (neither side has IO),
    // display-yes-no IO so the controller is happy with Just Works,
    // fixed passkey 000000 in case Security Manager asks for one.
    NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_YESNO);
    NimBLEDevice::setSecurityPasskey((uint32_t)0);
    NimBLEDevice::setSecurityAuth(/*bonding=*/true, /*mitm=*/false, /*sc=*/true);

#ifdef BENCH_HID_PUBLIC
    if (s_state.bench_server == nullptr) {
        s_state.bench_server = NimBLEDevice::createServer();
        NimBLEService *bench = s_state.bench_server->createService(UUID_BENCH_SERVICE);
        s_state.bench_write_char = bench->createCharacteristic(
            UUID_BENCH_HID_WRITE,
            NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR
        );
        s_state.bench_write_char->setCallbacks(&s_bench_write_callbacks);
        bench->start();

        // IMPORTANT: the bench service and the gamepad scan share the
        // single 2.4GHz radio. Configure scan-response advertising so the
        // device shows up as "CombatRobot-v2" in scan results; without
        // this, the scan results come back empty even when the radio is
        // listening for gamepad advertisements.
        NimBLEAdvertising *advertising = NimBLEDevice::getAdvertising();
        advertising->addServiceUUID(UUID_BENCH_SERVICE);
        advertising->setScanResponse(true);
        advertising->setMinPreferred(0x06);
        advertising->setMaxPreferred(0x12);
        // 0 = advertise forever. PC bench tools probe our hostname; we
        // want to stay visible so a desktop scanner can find us too.
        ESP_LOGI(TAG, "advertising + bench service up");
        ESP_LOGI(TAG, "PC bench BLE service + advertising started");
    }
#else
    // Default builds: do NOT expose the unauthenticated bench GATT
    // characteristic. Anyone in BLE range who knows UUID_BENCH_SERVICE
    // could otherwise write synthetic HID frames and drive the weapon.
    // The HTTP-side bench endpoints under /api/bench/ are already gated
    // by this same macro; the BLE side now matches.
#endif  // BENCH_HID_PUBLIC
    return ESP_OK;
}

esp_err_t ble_gamepad_start(void) {
    uint8_t count = nvs_get_count();
    // Boot remains IDLE so the SoftAP / web UI is reachable on the shared
    // 2.4 GHz radio. If a whitelisted controller already exists, arm
    // auto_reconnect so the poll loop keeps scanning for it; the user
    // does not have to re-click "Enter Pairing Mode" every power-cycle.
    s_state.pairing_state = PAIRING_STATE_IDLE;
    s_state.auto_reconnect = (count > 0);
    ESP_LOGI(TAG, "ble_gamepad_start: paired_count=%u, pairing_state=%d, auto_reconnect=%d",
             (unsigned)count, (int)s_state.pairing_state,
             (int)s_state.auto_reconnect);
    return ESP_OK;
}

void ble_gamepad_deinit(void) {
    stop_scan();
    if (s_state.client != nullptr) {
        if (s_state.client->isConnected()) s_state.client->disconnect();
        NimBLEDevice::deleteClient(s_state.client);
        s_state.client = nullptr;
    }
    if (s_state.pairing_timer != NULL) {
        esp_timer_stop(s_state.pairing_timer);
    }
    s_state.connected = false;
    // Same spinlock guard as the onDisconnect callback — see above.
    portENTER_CRITICAL(&s_state.lock);
    s_state.controller_state = ControllerState{};
    portEXIT_CRITICAL(&s_state.lock);
}

ControllerState ble_gamepad_get_state(void) {
    // Atomic copy under portENTER_CRITICAL — paired with the writes in
    // parse_8bitdo_report() / parse_standard_hid_report() so we never
    // return a ControllerState where some fields are from the old frame
    // and others from the new frame (torn read).
    portENTER_CRITICAL(&s_state.lock);
    ControllerState out = s_state.controller_state;
    portEXIT_CRITICAL(&s_state.lock);
    return out;
}

bool ble_gamepad_is_connected(void) {
    return s_state.connected;
}

PairingState ble_gamepad_get_pairing_state(void) {
    return s_state.pairing_state;
}

esp_err_t ble_gamepad_set_pairing_state(PairingState state) {
    PairingState prev = s_state.pairing_state;
    BLE_SERIALF("[BLE] set_pairing_state %d -> %d\r\n", (int)prev, (int)state);
    s_state.pairing_state = state;
    // Restating the static passkey here is cheap and protects against any
    // reset of the GAP security manager between boot and first pair.
    NimBLEDevice::setSecurityPasskey((uint32_t)0);
    if (s_state.pairing_timer != NULL) esp_timer_stop(s_state.pairing_timer);

    ESP_LOGI(TAG, "set_pairing_state: %d -> %d",
             (int)prev, (int)state);

    if (state == PAIRING_STATE_ACCEPT) {
        if (s_state.pairing_timer != NULL) {
            esp_timer_start_once(s_state.pairing_timer, BLE_PAIRING_WINDOW_MS * 1000ULL);
        }
        start_scan();
    } else {
        stop_scan();
    }
    return ESP_OK;
}

esp_err_t ble_gamepad_clear_paired_macs(void) {
    esp_err_t err = nvs_clear_all_macs();
    if (err != ESP_OK) return err;
    s_state.auto_reconnect = false;
    ble_gamepad_disconnect();
    return ble_gamepad_set_pairing_state(PAIRING_STATE_ACCEPT);
}

esp_err_t ble_gamepad_disconnect(void) {
    if (s_state.client != nullptr && s_state.client->isConnected()) {
        s_state.client->disconnect();
        return ESP_OK;
    }
    if (s_state.connected) {
        s_state.connected = false;
        s_state.client = nullptr;
        // Same spinlock guard as above — race-free zero-fill.
        portENTER_CRITICAL(&s_state.lock);
        s_state.controller_state = ControllerState{};
        portEXIT_CRITICAL(&s_state.lock);
        notify_connection_change(false, &s_state.connected_mac);
        return ESP_OK;
    }
    return ESP_ERR_INVALID_STATE;
}

void ble_gamepad_set_connection_callback(ble_connection_callback_t cb) {
    s_state.connection_cb = cb;
}

void ble_gamepad_poll(void) {
    if (s_state.connected) return;
    if (s_state.have_target) {
        BLE_SERIALF("[BLE] poll connecting deferred target\r\n");
        connect_to_target();
        return;
    }
    // Three reasons to be scanning right now:
    //   (1) User entered ACCEPT — open to any HID device.
    //   (2) We have a whitelisted controller and auto_reconnect is on.
    //   (3) Idle scan is disabled (DISABLED state) — bail.
    if (s_state.pairing_state == PAIRING_STATE_DISABLED) return;
    if (s_state.pairing_state != PAIRING_STATE_ACCEPT && !s_state.auto_reconnect) {
        return;
    }
    start_scan();
}
