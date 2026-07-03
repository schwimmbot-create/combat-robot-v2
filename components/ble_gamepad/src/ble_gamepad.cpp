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

#define BLE_SERIALF(...) do { \
    if (Serial) { \
        Serial.printf(__VA_ARGS__); \
    } \
} while (0)

static const NimBLEUUID UUID_HID((uint16_t)0x1812);
static const NimBLEUUID UUID_CHR_REPORT((uint16_t)0x2a4d);
static const NimBLEUUID UUID_CHR_REPORT_MAP((uint16_t)0x2a4b);
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
        s_state.controller_state = ControllerState{};
        notify_connection_change(false, &s_state.connected_mac);
        if (s_state.pairing_state != PAIRING_STATE_DISABLED) start_scan();
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
    // Real HID hosts do this; without it the 8BitDo tears down the link
    // shortly after we subscribe. The bytes are discarded — we only need
    // the read to register as activity on the link.
    NimBLERemoteCharacteristic *report_map = hid->getCharacteristic(UUID_CHR_REPORT_MAP);
    if (report_map != nullptr) {
        NimBLEAttValue map_data = report_map->readValue();
        (void)map_data;  // unused
    }

    // The 8BitDo Ultimate 2 publishes multiple 0x2A4D Report characteristics;
    // only the second (with notifiable property) carries actual gamepad input.
    // Iterate all Report characteristics and pick the first notifiable one,
    // then fall back to indicate if no notify-capable one is found.
    NimBLERemoteCharacteristic *report = nullptr;
    bool use_notify = true;
    std::vector<NimBLERemoteCharacteristic *> *chars = hid->getCharacteristics(true);
    if (chars != nullptr) {
        for (NimBLERemoteCharacteristic *chr : *chars) {
            if (chr == nullptr || !(chr->getUUID() == UUID_CHR_REPORT)) continue;
            if (chr->canNotify()) {
                report = chr;
                use_notify = true;
                break;
            }
            if (report == nullptr && chr->canIndicate()) {
                report = chr;
                use_notify = false;
            }
        }
    }

    if (report == nullptr) {
        ESP_LOGW(TAG, "No notifiable/indicatable HID report characteristic found");
        client->disconnect();
        NimBLEDevice::deleteClient(client);
        start_scan();
        return false;
    }

    BLE_SERIALF("[BLE] subscribing HID report use_notify=%d\r\n", (int)use_notify);
    if (!report->subscribe(use_notify, notify_cb)) {
        ESP_LOGW(TAG, "HID report subscribe failed");
        BLE_SERIALF("[BLE] HID subscribe failed\r\n");
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
        if (s_state.pairing_state != PAIRING_STATE_ACCEPT && !ble_mac_is_whitelisted(&mac)) {
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
    if (s_state.pairing_state != PAIRING_STATE_ACCEPT) {
        ESP_LOGD(TAG, "start_scan: skipping state=%d", (int)s_state.pairing_state);
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
    // scan deferred: ESP32-C3 BLE scans share the 2.4GHz radio with the
    // SoftAP. Boot must remain IDLE so the config UI loads reliably; the
    // user explicitly enters ACCEPT via /api/pair/start.
    s_state.pairing_state = PAIRING_STATE_IDLE;
    ESP_LOGI(TAG, "ble_gamepad_start: paired_count=%u, initial pairing_state=%d (scan deferred)",
             (unsigned)count, (int)s_state.pairing_state);
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

void ble_gamepad_poll(void) {
    if (s_state.connected) return;
    if (s_state.have_target) {
        BLE_SERIALF("[BLE] poll connecting deferred target\r\n");
        connect_to_target();
        return;
    }
    if (s_state.pairing_state != PAIRING_STATE_ACCEPT) return;
    start_scan();
}
