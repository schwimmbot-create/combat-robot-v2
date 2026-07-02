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

static const char *TAG = "ble_gamepad";

static const NimBLEUUID UUID_HID((uint16_t)0x1812);
static const NimBLEUUID UUID_CHR_REPORT((uint16_t)0x2a4d);
static const NimBLEUUID UUID_BENCH_SERVICE("7d2f0001-0f3a-4b8a-9b7d-2f4c9a000001");
static const NimBLEUUID UUID_BENCH_HID_WRITE("7d2f0002-0f3a-4b8a-9b7d-2f4c9a000001");

#define NVS_NAMESPACE       "ble_paired"
#define NVS_KEY_COUNT       "count"
#define NVS_KEY_MAC_FMT     "mac_%d"
#define BLE_PAIRING_WINDOW_MS 60000

static void start_scan(void);
static void stop_scan(void);
static void parse_hid_report(const uint8_t *data, uint16_t len);
static void notify_connection_change(bool connected, const ble_mac_t *mac);

static struct {
    PairingState pairing_state;
    ControllerState controller_state;
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
} s_state = {
    .pairing_state = PAIRING_STATE_IDLE,
    .connected = false,
    .connection_cb = NULL,
    .pairing_timer = NULL,
    .client = NULL,
    .bench_server = NULL,
    .bench_write_char = NULL,
    .have_target = false,
    .scan_active = false,
};

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
    if (count >= BLE_MAX_PAIRED_CONTROLLERS) return ESP_ERR_NO_MEM;
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

static void parse_hid_report(const uint8_t *data, uint16_t len) {
    if (len < 8) return;

    auto scale_axis_full = [](uint8_t v) -> int {
        return ((int)v - 127) * 4;
    };

    s_state.controller_state.leftStickX = scale_axis_full(data[0]);
    s_state.controller_state.leftStickY = scale_axis_full(data[1]);
    s_state.controller_state.rightStickX = scale_axis_full(data[2]);
    s_state.controller_state.rightStickY = scale_axis_full(data[3]);

    if (len >= 6) {
        s_state.controller_state.buttons = data[4] | (data[5] << 8);
    }
    if (len >= 8) {
        s_state.controller_state.leftTrigger = (int)data[6] * 4;
        s_state.controller_state.rightTrigger = (int)data[7] * 4;
    }
    if (len >= 9) {
        switch (data[8]) {
            case 0: s_state.controller_state.dpad = 0x01; break;
            case 1: s_state.controller_state.dpad = 0x01 | 0x04; break;
            case 2: s_state.controller_state.dpad = 0x04; break;
            case 3: s_state.controller_state.dpad = 0x02 | 0x04; break;
            case 4: s_state.controller_state.dpad = 0x02; break;
            case 5: s_state.controller_state.dpad = 0x02 | 0x08; break;
            case 6: s_state.controller_state.dpad = 0x08; break;
            case 7: s_state.controller_state.dpad = 0x01 | 0x08; break;
            default: s_state.controller_state.dpad = 0; break;
        }
    }
}

// --- NimBLE-Arduino callbacks -------------------------------------------

class BenchWriteCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic *chr) override {
        std::string value = chr->getValue();
        if (value.empty()) return;
        parse_hid_report(reinterpret_cast<const uint8_t *>(value.data()), value.size());

        static const ble_mac_t bench_mac = {{0x02, 0x00, 0x00, 0x00, 0xbe, 0x7c}};
        s_state.connected_mac = bench_mac;
        if (!s_state.connected) notify_connection_change(true, &s_state.connected_mac);
        ESP_LOGD(TAG, "bench HID frame accepted (%u bytes)", (unsigned)value.size());
    }
};

static BenchWriteCallbacks s_bench_write_callbacks;

static void notify_cb(NimBLERemoteCharacteristic *chr, uint8_t *data,
                      size_t len, bool is_notify) {
    (void)chr;
    (void)is_notify;
    parse_hid_report(data, (uint16_t)len);
}

class GamepadClientCallbacks : public NimBLEClientCallbacks {
    void onDisconnect(NimBLEClient *client) override {
        (void)client;
        ESP_LOGW(TAG, "Controller disconnected");
        s_state.connected = false;
        s_state.controller_state = ControllerState{};
        notify_connection_change(false, &s_state.connected_mac);
        if (s_state.pairing_state != PAIRING_STATE_DISABLED) start_scan();
    }
};

static GamepadClientCallbacks s_client_callbacks;

static bool connect_to_target(void) {
    if (!s_state.have_target) return false;

    stop_scan();
    NimBLEClient *client = NimBLEDevice::createClient();
    if (client == nullptr) return false;
    client->setClientCallbacks(&s_client_callbacks, false);

    ESP_LOGI(TAG, "Connecting to %s", s_state.target.getAddress().toString().c_str());
    if (!client->connect(&s_state.target)) {
        ESP_LOGW(TAG, "Connect failed");
        NimBLEDevice::deleteClient(client);
        start_scan();
        return false;
    }

    NimBLERemoteService *hid = client->getService(UUID_HID);
    if (hid == nullptr) {
        ESP_LOGW(TAG, "Connected device has no HID service");
        client->disconnect();
        NimBLEDevice::deleteClient(client);
        start_scan();
        return false;
    }

    NimBLERemoteCharacteristic *report = hid->getCharacteristic(UUID_CHR_REPORT);
    if (report == nullptr || !report->canNotify()) {
        ESP_LOGW(TAG, "HID report characteristic not found or not notifiable");
        client->disconnect();
        NimBLEDevice::deleteClient(client);
        start_scan();
        return false;
    }

    if (!report->subscribe(true, notify_cb)) {
        ESP_LOGW(TAG, "HID notification subscribe failed");
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
    notify_connection_change(true, &s_state.connected_mac);
    ESP_LOGI(TAG, "Subscribed to HID reports");
    return true;
}

class GamepadAdvertisedDeviceCallbacks : public NimBLEAdvertisedDeviceCallbacks {
    void onResult(NimBLEAdvertisedDevice *device) override {
        if (!device->isAdvertisingService(UUID_HID)) return;

        ble_mac_t mac;
        address_to_mac(device->getAddress(), &mac);
        if (s_state.pairing_state != PAIRING_STATE_ACCEPT && !ble_mac_is_whitelisted(&mac)) {
            return;
        }

        s_state.target = *device;
        s_state.have_target = true;
        connect_to_target();
    }
};

static GamepadAdvertisedDeviceCallbacks s_scan_callbacks;

// --- Scan / connection state ---------------------------------------------

static void notify_connection_change(bool connected, const ble_mac_t *mac) {
    s_state.connected = connected;
    if (s_state.connection_cb) s_state.connection_cb(connected, mac);
}

static void start_scan(void) {
    if (s_state.pairing_state == PAIRING_STATE_DISABLED) {
        ESP_LOGD(TAG, "start_scan: skipping (DISABLED)");
        return;
    }
    if (s_state.connected) {
        ESP_LOGD(TAG, "start_scan: already connected");
        return;
    }
    // Always reset scan_active before starting; NimBLE reports start()
    // success but doesn't tell us when the scan fully finished.
    NimBLEScan *scan = NimBLEDevice::getScan();
    if (scan->isScanning()) {
        ESP_LOGD(TAG, "start_scan: scan already running");
        s_state.scan_active = true;
        return;
    }
    scan->setAdvertisedDeviceCallbacks(&s_scan_callbacks, false);
    scan->setActiveScan(true);
    scan->setInterval(45);
    scan->setWindow(15);
    bool ok = scan->start(0, nullptr, false);
    s_state.scan_active = ok;
    ESP_LOGI(TAG, "start_scan: ok=%d state=%d", (int)ok, (int)s_state.pairing_state);
}

static void stop_scan(void) {
    NimBLEScan *scan = NimBLEDevice::getScan();
    if (scan->isScanning()) scan->stop();
    s_state.scan_active = false;
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
    NimBLEDevice::setSecurityAuth(true, true, true);

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
    return ESP_OK;
}

esp_err_t ble_gamepad_start(void) {
    uint8_t count = nvs_get_count();
    s_state.pairing_state = (count == 0) ? PAIRING_STATE_ACCEPT : PAIRING_STATE_IDLE;
    ESP_LOGI(TAG, "ble_gamepad_start: paired_count=%u, initial pairing_state=%d",
             (unsigned)count, (int)s_state.pairing_state);
    // Even if we start in IDLE (paired device already in NVS), the scan
    // watches for that single paired MAC and auto-reconnects. If we're
    // ACCEPT (no paired controllers), scan filters on HID service UUID
    // and accepts any gamepad.
    start_scan();
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
    s_state.controller_state = ControllerState{};
}

ControllerState ble_gamepad_get_state(void) {
    return s_state.controller_state;
}

bool ble_gamepad_is_connected(void) {
    return s_state.connected;
}

PairingState ble_gamepad_get_pairing_state(void) {
    return s_state.pairing_state;
}

esp_err_t ble_gamepad_set_pairing_state(PairingState state) {
    PairingState prev = s_state.pairing_state;
    s_state.pairing_state = state;
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
    ble_gamepad_disconnect();
    return ble_gamepad_set_pairing_state(PAIRING_STATE_ACCEPT);
}

esp_err_t ble_gamepad_disconnect(void) {
    if (s_state.client != nullptr && s_state.client->isConnected()) {
        s_state.client->disconnect();
        return ESP_OK;
    }
    return ESP_ERR_INVALID_STATE;
}

void ble_gamepad_set_connection_callback(ble_connection_callback_t cb) {
    s_state.connection_cb = cb;
}
