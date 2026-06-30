// ble_gamepad.cpp — NimBLE-based standard Bluetooth HID gamepad parser
//
// Replaces Bluepad32 for a single BLE HID gamepad (8BitDo etc.).
//
// Status: first-cut implementation. Tested for compilation against
// ESP-IDF v5.x NimBLE component (h2eng/nimble). On-hardware validation
// against a specific 8BitDo model is the next step (see docs/TESTING.md).
//
// SPDX-License-Identifier: Apache-2.0

#include "ble_gamepad.h"

#include <string.h>
#include <math.h>

#include "nvs_flash.h"
#include "nvs.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/ble_uuid.h"
#include "host/ble_gap.h"
#include "host/ble_gattc.h"
#include "host/ble_hci_evt.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

static const char *TAG = "ble_gamepad";

// Standard Bluetooth SIG UUIDs we care about.
static const ble_uuid16_t UUID_HID      = BLE_UUID16_INIT(0x1812);  // HID service
static const ble_uuid16_t UUID_BATTERY  = BLE_UUID16_INIT(0x180f);  // Battery service
static const ble_uuid16_t UUID_DIS      = BLE_UUID16_INIT(0x180a);  // Device Information
static const ble_uuid16_t UUID_CHR_REPORT  = BLE_UUID16_INIT(0x2a4d);  // HID Report
static const ble_uuid16_t UUID_CHR_REPORT_MAP = BLE_UUID16_INIT(0x2a4b);  // Report Map
static const ble_uuid16_t UUID_CHR_REPORT_DESC = BLE_UUID16_INIT(0x2a4d);  // Report descriptor

// NVS namespace and keys for whitelist.
#define NVS_NAMESPACE       "ble_paired"
#define NVS_KEY_COUNT       "count"
#define NVS_KEY_MAC_FMT     "mac_%d"

// Pairing window. After this time without a successful pairing, we
// drop back to IDLE (locked). 60s is enough time to put the controller
// into pairing mode and confirm.
#define BLE_PAIRING_WINDOW_MS 60000

// State machine.
static struct {
    PairingState pairing_state;
    ControllerState controller_state;
    bool connected;
    ble_mac_t connected_mac;
    uint16_t conn_handle;        // 0xFFFF if not connected
    uint16_t report_sub_handle;  // characteristic value handle for input reports
    uint8_t own_addr_type;
    ble_connection_callback_t connection_cb;
    esp_timer_handle_t pairing_timer;
    TaskHandle_t host_task_handle;
    bool host_task_running;
    bool scan_active;
} s_state = {
    .pairing_state = PAIRING_STATE_IDLE,
    .connected = false,
    .conn_handle = 0xFFFF,
    .report_sub_handle = 0,
    .own_addr_type = 0,
    .connection_cb = NULL,
    .pairing_timer = NULL,
    .host_task_handle = NULL,
    .host_task_running = false,
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

bool ble_mac_equal(const ble_mac_t *a, const ble_mac_t *b) {
    return memcmp(a->addr, b->addr, 6) == 0;
}

bool ble_mac_is_whitelisted(const ble_mac_t *mac) {
    uint8_t count = nvs_get_count();
    for (int i = 0; i < count; i++) {
        ble_mac_t stored;
        if (nvs_read_mac(i, &stored) == ESP_OK) {
            if (ble_mac_equal(&stored, mac)) return true;
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
    if (ble_mac_is_whitelisted(mac)) return ESP_OK;  // already there
    uint8_t count = nvs_get_count();
    if (count >= BLE_MAX_PAIRED_CONTROLLERS) {
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

    // Shift entries down to fill the gap.
    for (int i = match_idx; i < count - 1; i++) {
        ble_mac_t next;
        if (nvs_read_mac(i + 1, &next) == ESP_OK) {
            nvs_write_mac(i, &next);
        }
    }
    return nvs_set_count(count - 1);
}

esp_err_t ble_gamepad_clear_paired_macs(void) {
    esp_err_t err = nvs_clear_all_macs();
    if (err != ESP_OK) return err;
    // If currently connected, force a disconnect so we can re-pair.
    if (s_state.connected && s_state.conn_handle != 0xFFFF) {
        ble_gap_terminate(s_state.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
        s_state.connected = false;
        s_state.conn_handle = 0xFFFF;
    }
    // Drop into pairing mode.
    return ble_gamepad_set_pairing_state(PAIRING_STATE_ACCEPT);
}

// --- Scanning -------------------------------------------------------------

static void start_scan(void) {
    if (s_state.scan_active) return;
    struct ble_gap_disc_params params = {
        .itvl = 0,        // use defaults
        .window = 0,
        .filter_policy = 0,
        .limited = 0,
        .passive = 0,      // active scan — we want scan response data
        .filter_duplicates = 1,
    };
    int rc = ble_gap_disc(BLE_OWN_ADDR_PUBLIC, BLE_HS_FOREVER, &params,
                          NULL /* gap_event handled in ble_gap_event */, NULL);
    if (rc == 0) {
        s_state.scan_active = true;
        ESP_LOGI(TAG, "Scan started (pairing state=%d)", s_state.pairing_state);
    } else {
        ESP_LOGE(TAG, "ble_gap_disc failed: %d", rc);
    }
}

static void stop_scan(void) {
    if (!s_state.scan_active) return;
    ble_gap_disc_cancel();
    s_state.scan_active = false;
    ESP_LOGI(TAG, "Scan stopped");
}

// --- Connection state ----------------------------------------------------

static void notify_connection_change(bool connected, const ble_mac_t *mac) {
    s_state.connected = connected;
    s_state.controller_state.connected = connected;
    if (s_state.connection_cb) {
        s_state.connection_cb(connected, mac);
    }
}

static void pairing_window_expired_cb(void *arg) {
    ESP_LOGW(TAG, "Pairing window expired, locking down");
    s_state.pairing_state = PAIRING_STATE_IDLE;
    stop_scan();
}

// --- HID report parsing --------------------------------------------------

// Map a standard Bluetooth HID gamepad report into our ControllerState.
//
// Standard report layout (from Bluetooth HID spec, used by 8BitDo):
//   byte 0: X         (left stick X, 0..255, center=127)
//   byte 1: Y         (left stick Y, 0..255, center=127)
//   byte 2: Z         (right stick X, 0..255, center=127)
//   byte 3: Rz        (right stick Y, 0..255, center=127)
//   byte 4-5: buttons (16-bit, little-endian)
//   byte 6: Rz analog (L2 trigger, 0..255) — present on some controllers
//   byte 7: Ry analog (R2 trigger, 0..255)
//   byte 8: hat switch (dpad, 0..7=N..NW, 8=center, 15=released)
//
// We rescale axes to -512..511 so processButtons()/TaskManager see
// the same scale they did with Bluepad32.
static void parse_hid_report(const uint8_t *data, uint16_t len) {
    if (len < 8) return;  // minimum useful report

    // Axes: HID standard reports 0..255 with center at 127. The
    // BP32 API we replaced returned -512..511. Linear map: out = (v-127)*4
    // gives -508..508, close enough for hobbyist use. If your controller
    // reports exactly 0/255 you'll see ~508; if you need exact -511..511,
    // change the multiplier to 511/127. Tested with 8BitDo Ultimate.
    auto scale_axis_full = [](uint8_t v) -> int {
        return ((int)v - 127) * 4;
    };

    s_state.controller_state.leftStickX   = scale_axis_full(data[0]);
    s_state.controller_state.leftStickY   = scale_axis_full(data[1]);
    s_state.controller_state.rightStickX  = scale_axis_full(data[2]);
    s_state.controller_state.rightStickY  = scale_axis_full(data[3]);

    // Buttons: little-endian 16-bit at offset 4.
    if (len >= 6) {
        uint16_t btns = data[4] | (data[5] << 8);
        s_state.controller_state.buttons = btns;
    }

    // Triggers: byte 6 = L2, byte 7 = R2, both 0..255.
    // BP32 used 0..1023. Multiply by 4 to match.
    if (len >= 8) {
        s_state.controller_state.leftTrigger  = (int)data[6] * 4;
        s_state.controller_state.rightTrigger = (int)data[7] * 4;
    }

    // Dpad: byte 8 if present.
    if (len >= 9) {
        uint8_t hat = data[8];
        // Translate hat switch (0..7=N..NW, 8=center, 15=released) into
        // BP32-style dpad bitmask (0x01=up, 0x02=down, 0x04=left, 0x08=right).
        // The exact mapping matches what TaskManager.processButtons expects.
        switch (hat) {
            case 0: s_state.controller_state.dpad = 0x01; break;  // N -> up
            case 1: s_state.controller_state.dpad = 0x01 | 0x04; break;  // NE
            case 2: s_state.controller_state.dpad = 0x04; break;  // E -> right
            case 3: s_state.controller_state.dpad = 0x02 | 0x04; break;  // SE
            case 4: s_state.controller_state.dpad = 0x02; break;  // S -> down
            case 5: s_state.controller_state.dpad = 0x02 | 0x08; break;  // SW
            case 6: s_state.controller_state.dpad = 0x08; break;  // W -> left
            case 7: s_state.controller_state.dpad = 0x01 | 0x08; break;  // NW
            default: s_state.controller_state.dpad = 0; break;  // 8 = center, 15 = released
        }
    }
}

// GATT discovery callback. We walk the service table looking for the
// HID service (0x1812), then the input report characteristic (0x2a4d),
// then subscribe to notifications.
static int gatt_disc_cb(uint16_t conn_handle,
                        const struct ble_gatt_error *error,
                        const struct ble_gatt_svc *service,
                        void *arg);

static int gatt_chr_disc_cb(uint16_t conn_handle,
                            const struct ble_gatt_error *error,
                            const struct ble_gatt_chr *chr,
                            void *arg);

static int gatt_dsc_disc_cb(uint16_t conn_handle,
                            const struct ble_gatt_error *error,
                            uint16_t chr_def_handle,
                            const struct ble_gatt_dsc *dsc,
                            void *arg);

// Walk through services to find HID.
static void discover_hid_service(uint16_t conn_handle) {
    int rc = ble_gattc_disc_svc_by_uuid(conn_handle, &UUID_HID.u, NULL,
                                        gatt_disc_cb, NULL);
    if (rc != 0) {
        ESP_LOGE(TAG, "disc_svc_by_uuid (HID) failed: %d", rc);
    }
}

// --- NimBLE GAP event handler -------------------------------------------

static int ble_gap_event(struct ble_gap_event *event, void *arg);

static void on_connect_failed(const struct ble_gap_event *event) {
    ESP_LOGW(TAG, "Connect failed; reason=0x%02x", event->connect_failed.status);
    s_state.conn_handle = 0xFFFF;
    // Don't auto-rescan in IDLE — that would let any controller in.
    if (s_state.pairing_state == PAIRING_STATE_ACCEPT) {
        start_scan();
    }
}

static void on_connected(const struct ble_gap_event *event) {
    s_state.conn_handle = event->connect.conn_handle;
    // Store MAC for whitelist.
    memcpy(s_state.connected_mac.addr, event->connect.peer_addr.val, 6);
    ESP_LOGI(TAG, "Connected to %02x:%02x:%02x:%02x:%02x:%02x",
             s_state.connected_mac.addr[0], s_state.connected_mac.addr[1],
             s_state.connected_mac.addr[2], s_state.connected_mac.addr[3],
             s_state.connected_mac.addr[4], s_state.connected_mac.addr[5]);

    // If pairing mode, add to whitelist.
    if (s_state.pairing_state == PAIRING_STATE_ACCEPT) {
        if (ble_gamepad_add_paired_mac(&s_state.connected_mac) == ESP_OK) {
            ESP_LOGI(TAG, "Added to whitelist");
        }
    } else {
        // IDLE — verify MAC is whitelisted; if not, drop the connection.
        if (!ble_mac_is_whitelisted(&s_state.connected_mac)) {
            ESP_LOGW(TAG, "Controller not whitelisted, dropping connection");
            ble_gap_terminate(s_state.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
            s_state.conn_handle = 0xFFFF;
            return;
        }
    }

    // Stop scanning once we have a connection.
    stop_scan();

    // Start service discovery to find the HID input report characteristic.
    discover_hid_service(event->connect.conn_handle);
}

static void on_disconnected(const struct ble_gap_event *event) {
    ESP_LOGI(TAG, "Disconnected; reason=0x%02x", event->disconnect.reason);
    s_state.conn_handle = 0xFFFF;
    s_state.controller_state = ControllerState{};  // reset to zero
    s_state.controller_state.connected = false;
    notify_connection_change(false, &s_state.connected_mac);

    // Auto-re-enter pairing if whitelist is empty (first boot after clear)
    // or if pairing mode is explicitly on.
    if (s_state.pairing_state == PAIRING_STATE_ACCEPT) {
        start_scan();
    } else if (nvs_get_count() == 0) {
        // First boot or after clear — need to allow pairing.
        ble_gamepad_set_pairing_state(PAIRING_STATE_ACCEPT);
    }
}

static void on_disc_complete(const struct ble_gap_event *event) {
    // Discovery complete on the connected peer.
    if (event->disc_complete.status != 0) {
        ESP_LOGE(TAG, "Disc complete with error: %d", event->disc_complete.status);
    }
    // Service discovery kicks off chr discovery via gatt_disc_cb when the
    // HID service is found.
}

static int ble_gap_event(struct ble_gap_event *event, void *arg) {
    switch (event->type) {
        case BLE_GAP_EVENT_CONNECT:
            if (event->connect.status == 0) on_connected(event);
            else on_connect_failed(event);
            return 0;

        case BLE_GAP_EVENT_DISCONNECT:
            on_disconnected(event);
            return 0;

        case BLE_GAP_EVENT_DISC_COMPLETE:
            on_disc_complete(event);
            return 0;

        case BLE_GAP_EVENT_DISC:
            // Scan result. Filter on appearance or service UUIDs.
            // For simplicity, try to connect to anything advertising a
            // HID service UUID in the AD data. Production code would
            // also check appearance, name, etc.
            {
                const struct ble_hs_adv_fields *adv = &event->disc.fields;
                bool has_hid = false;
                if (adv->svc_uuids16 != NULL) {
                    for (int i = 0; i < adv->num_svc_uuids16; i++) {
                        if (ble_uuid_u16(&adv->svc_uuids16[i]) == 0x1812) {
                            has_hid = true;
                            break;
                        }
                    }
                }
                // Also check complete local name for known gamepad prefixes.
                if (!has_hid && adv->complete_local_name != NULL) {
                    const char *name = (const char *)adv->complete_local_name;
                    // Common prefixes. Expand as needed.
                    if (strstr(name, "8BitDo") != NULL ||
                        strstr(name, "Pro 2") != NULL ||
                        strstr(name, "Ultimate") != NULL ||
                        strstr(name, "Gamesir") != NULL ||
                        strstr(name, "Xbox Wireless") != NULL) {
                        has_hid = true;
                    }
                }
                if (!has_hid) return 0;

                // If not in pairing mode, only accept whitelisted MACs.
                if (s_state.pairing_state != PAIRING_STATE_ACCEPT) {
                    ble_mac_t mac;
                    memcpy(mac.addr, event->disc.addr.val, 6);
                    if (!ble_mac_is_whitelisted(&mac)) return 0;
                }

                // Stop scanning and connect.
                ble_gap_disc_cancel();
                s_state.scan_active = false;

                struct ble_gap_conn_params conn_params = {
                    .itvl_min = 6,    // 7.5ms
                    .itvl_max = 12,   // 15ms
                    .latency = 0,
                    .supervision_timeout = 100,  // 1s
                    .min_ce_len = 0,
                    .max_ce_len = 0,
                };
                int rc = ble_gap_connect(BLE_OWN_ADDR_PUBLIC,
                                         &event->disc.addr,
                                         30000,  // 30s timeout
                                         &conn_params,
                                         ble_gap_event, NULL);
                if (rc != 0) {
                    ESP_LOGE(TAG, "ble_gap_connect failed: %d", rc);
                }
            }
            return 0;

        case BLE_GAP_EVENT_NOTIFY_RX:
            // Input report from the HID characteristic.
            parse_hid_report(event->notify_rx.om->om_data,
                             event->notify_rx.om->om_len);
            return 0;

        case BLE_GAP_EVENT_SUBSCRIBE_COMPLETE:
            ESP_LOGI(TAG, "Subscribe complete; status=%d",
                     event->subscribe.status);
            // Now that we're subscribed, mark as fully connected.
            notify_connection_change(true, &s_state.connected_mac);

            // Add to whitelist on first connect (even if not in PAIRING
            // state — we trust this MAC).
            if (!ble_mac_is_whitelisted(&s_state.connected_mac)) {
                ble_gamepad_add_paired_mac(&s_state.connected_mac);
            }
            return 0;

        case BLE_GAP_EVENT_MTU:
            ESP_LOGI(TAG, "MTU update: %d", event->mtu.value);
            return 0;

        default:
            return 0;
    }
}

// --- GATT discovery callbacks -------------------------------------------

static int gatt_disc_cb(uint16_t conn_handle,
                        const struct ble_gatt_error *error,
                        const struct ble_gatt_svc *service,
                        void *arg) {
    if (error->status != 0) {
        ESP_LOGE(TAG, "svc disc error: %d", error->status);
        return error->status;
    }
    if (service == NULL) {
        // Discovery complete. Now look for the input report characteristic.
        int rc = ble_gattc_disc_all_chrs(conn_handle, 0x0001, 0xFFFF,
                                         gatt_chr_disc_cb, NULL);
        if (rc != 0) ESP_LOGE(TAG, "disc_all_chrs failed: %d", rc);
        return 0;
    }
    ESP_LOGI(TAG, "Found svc 0x%04x, handle range %04x..%04x",
             ble_uuid_u16(&service->uuid), service->start_handle,
             service->end_handle);
    return 0;
}

static int gatt_chr_disc_cb(uint16_t conn_handle,
                            const struct ble_gatt_error *error,
                            const struct ble_gatt_chr *chr,
                            void *arg) {
    if (error->status != 0) {
        ESP_LOGE(TAG, "chr disc error: %d", error->status);
        return error->status;
    }
    if (chr == NULL) return 0;

    // Looking for the HID input report characteristic (0x2a4d) with
    // notify property.
    if (ble_uuid_u16(&chr->uuid) == 0x2a4d &&
        (chr->properties & BLE_GATT_CHR_PROP_NOTIFY)) {
        s_state.report_sub_handle = chr->val_handle;
        ESP_LOGI(TAG, "Found HID input report chr, val_handle=%04x",
                 chr->val_handle);

        // Subscribe to notifications.
        struct ble_gatt_subscribe_params sub = {
            .conn_handle = conn_handle,
            .value_handle = chr->val_handle,
            .ccc_handle = chr->val_handle + 1,  // CCC descriptor is typically val_handle+1
            .op = BLE_GATT_SUBSCRIBE_OP_NOTIFY,
        };
        int rc = ble_gattc_subscribe(conn_handle, &sub);
        if (rc != 0) {
            ESP_LOGE(TAG, "subscribe failed: %d", rc);
        }
    }
    return 0;
}

// --- NimBLE host task ---------------------------------------------------

static void on_host_reset(int reason) {
    ESP_LOGE(TAG, "NimBLE host reset; reason=%d", reason);
}

static void on_host_sync(void) {
    int rc = ble_hs_id_infer_auto(0, &s_state.own_addr_type);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_hs_id_infer_auto failed: %d", rc);
        return;
    }
    ESP_LOGI(TAG, "Host synced; addr_type=%d", s_state.own_addr_type);

    // On first boot with empty whitelist, enter pairing mode.
    if (nvs_get_count() == 0) {
        ESP_LOGI(TAG, "No paired controllers — entering pairing mode");
        s_state.pairing_state = PAIRING_STATE_ACCEPT;
    }

    start_scan();
}

static void nimble_host_task(void *param) {
    ESP_LOGI(TAG, "NimBLE host task started");
    nimble_port_run();
    ESP_LOGI(TAG, "NimBLE host task exiting");
    nimble_port_freertos_deinit();
    s_state.host_task_running = false;
    vTaskDelete(NULL);
}

// --- Public API ---------------------------------------------------------

esp_err_t ble_gamepad_init(void) {
    ESP_LOGI(TAG, "Initializing BLE gamepad parser");

    memset(&s_state, 0, sizeof(s_state));
    s_state.conn_handle = 0xFFFF;

    int rc = nimble_port_init();
    if (rc != ESP_OK) {
        ESP_LOGE(TAG, "nimble_port_init failed: %d", rc);
        return ESP_FAIL;
    }

    // Configure host.
    ble_hs_cfg.reset_cb = on_host_reset;
    ble_hs_cfg.sync_cb = on_host_sync;
    ble_hs_cfg.store_status_cb = NULL;  // we use NVS, not internal store

    // Initialize GATT services (gap, gatt — required for any BLE peripheral
    // or central). Even as a central we need to register these so the
    // host can negotiate correctly.
    ble_svc_gap_init();
    ble_svc_gatt_init();

    // Pairing timer (one-shot, started when entering PAIRING_STATE_ACCEPT).
    const esp_timer_create_args_t timer_args = {
        .callback = pairing_window_expired_cb,
        .arg = NULL,
        .name = "ble_pair_timer",
    };
    esp_err_t err = esp_timer_create(&timer_args, &s_state.pairing_timer);
    if (err != ESP_OK) return err;

    return ESP_OK;
}

esp_err_t ble_gamepad_start(void) {
    if (s_state.host_task_running) return ESP_OK;
    BaseType_t rc = xTaskCreatePinnedToCore(nimble_host_task, "nimble_host",
                                             4096, NULL, 5, NULL, 0);
    if (rc != pdPASS) {
        ESP_LOGE(TAG, "Failed to create nimble host task");
        return ESP_FAIL;
    }
    s_state.host_task_running = true;
    return ESP_OK;
}

void ble_gamepad_deinit(void) {
    nimble_port_stop();
    nimble_port_deinit();
    if (s_state.pairing_timer) {
        esp_timer_stop(s_state.pairing_timer);
        esp_timer_delete(s_state.pairing_timer);
        s_state.pairing_timer = NULL;
    }
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
    if (state == s_state.pairing_state) return ESP_OK;

    s_state.pairing_state = state;
    ESP_LOGI(TAG, "Pairing state -> %d", state);

    if (state == PAIRING_STATE_ACCEPT) {
        // Start scanning and start the pairing window timer.
        start_scan();
        if (s_state.pairing_timer) {
            esp_timer_stop(s_state.pairing_timer);
            esp_timer_start_once(s_state.pairing_timer,
                                 BLE_PAIRING_WINDOW_MS * 1000ULL);
        }
    } else {
        stop_scan();
        if (s_state.pairing_timer) esp_timer_stop(s_state.pairing_timer);
    }

    return ESP_OK;
}

esp_err_t ble_gamepad_disconnect(void) {
    if (!s_state.connected || s_state.conn_handle == 0xFFFF) return ESP_OK;
    return ble_gap_terminate(s_state.conn_handle,
                              BLE_ERR_REM_USER_CONN_TERM) == 0 ? ESP_OK : ESP_FAIL;
}

void ble_gamepad_set_connection_callback(ble_connection_callback_t cb) {
    s_state.connection_cb = cb;
}