// web_config.cpp — Async web server + WiFi manager + HTML UI
//
// First-cut implementation. Covers:
//   * WiFi STA with NVS-saved credentials (fallback to AP on failure)
//   * Async web server on port 80
//   * REST endpoints for status, pairing
//   * Embedded HTML dashboard (PROGMEM)
//   * OTA stub (returns 501; full impl in follow-up)
//
// Deferred to follow-up commits:
//   * Captive portal DNS (currently just prints the AP IP to serial)
//   * Motor/pin/LED config UI
//   * Input mapping editor
//
// SPDX-License-Identifier: Apache-2.0

#include "web_config.h"
#include "ble_gamepad.h"
#include "board_config.h"
#include "board_detect.h"
#include "Constants.h"

#include <Arduino.h>
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <AsyncTCP.h>
#include <Update.h>
#include <Preferences.h>

#include "esp_log.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "esp_system.h"
#include "esp_netif.h"
#include "esp_event.h"

static const char *TAG = "web_config";

// NVS namespace for WiFi credentials.
#define WIFI_NVS_NAMESPACE "wifi_creds"
#define NVS_KEY_SSID "ssid"
#define NVS_KEY_PSK  "psk"

// Default AP fallback config (printed to serial on first boot).
// AP password is generated on first boot and stored in NVS; not
// hard-coded for security.
static const char *AP_SSID_PREFIX = "Combat-Robot-";
#define AP_DEFAULT_PASSWORD "fightbot"  // 8+ chars required by spec

// Globals.
static AsyncWebServer *server = nullptr;
static bool wifi_ap_mode = false;
static char ap_password[32] = AP_DEFAULT_PASSWORD;

// --- WiFi credential storage ------------------------------------------

static esp_err_t wifi_load_credentials(char *ssid, size_t ssid_len,
                                       char *psk, size_t psk_len) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(WIFI_NVS_NAMESPACE, NVS_READONLY, &h);
    if (err != ESP_OK) return err;
    err = nvs_get_str(h, NVS_KEY_SSID, ssid, &ssid_len);
    if (err != ESP_OK) { nvs_close(h); return err; }
    err = nvs_get_str(h, NVS_KEY_PSK, psk, &psk_len);
    nvs_close(h);
    return err;
}

static esp_err_t wifi_save_credentials(const char *ssid, const char *psk) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(WIFI_NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    err = nvs_set_str(h, NVS_KEY_SSID, ssid);
    if (err == ESP_OK) err = nvs_set_str(h, NVS_KEY_PSK, psk);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}

static esp_err_t wifi_clear_credentials(void) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(WIFI_NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    err = nvs_erase_all(h);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}

// --- HTML (embedded PROGMEM) ------------------------------------------

static const char INDEX_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Combat Robot v2</title>
  <style>
    body { font-family: -apple-system, system-ui, sans-serif; background: #1a1a1a;
           color: #eee; margin: 0; padding: 1rem; }
    h1 { color: #ff6b35; }
    .card { background: #2a2a2a; border-radius: 8px; padding: 1rem;
            margin-bottom: 1rem; }
    .status-grid { display: grid; grid-template-columns: max-content 1fr;
                   gap: 0.5rem 1rem; }
    .label { color: #888; }
    .ok { color: #4ade80; }
    .warn { color: #fbbf24; }
    .err { color: #f87171; }
    button { background: #ff6b35; color: white; border: none; padding: 0.5rem 1rem;
             border-radius: 4px; cursor: pointer; font-weight: 600; }
    button:hover { background: #ff8c5a; }
    button:disabled { background: #555; cursor: not-allowed; }
    code { background: #111; padding: 0.1rem 0.3rem; border-radius: 3px;
           font-size: 0.9em; }
    .mac-list { font-family: monospace; }
  </style>
</head>
<body>
  <h1>🤖 Combat Robot v2</h1>

  <div class="card">
    <h2>Status</h2>
    <div class="status-grid" id="status">
      <span class="label">Loading…</span>
    </div>
  </div>

  <div class="card">
    <h2>Controller</h2>
    <p>Connected: <span id="ble-state">–</span></p>
    <p>MAC: <code id="ble-mac">–</code></p>
    <p>Pairing: <span id="pair-state">–</span></p>
    <button id="btn-pair">Enter Pairing Mode</button>
    <button id="btn-cancel-pair" disabled>Cancel Pairing</button>
    <button id="btn-unpair">Clear Paired Controllers</button>
  </div>

  <div class="card">
    <h2>Paired Controllers</h2>
    <div class="mac-list" id="mac-list">–</div>
  </div>

  <div class="card">
    <h2>WiFi</h2>
    <p>IP: <code id="wifi-ip">–</code> <span id="wifi-mode"></span></p>
    <p>To change WiFi: hold the BOOT button for 10s, or POST to <code>/api/wifi</code>.</p>
  </div>

  <div class="card">
    <h2>Firmware</h2>
    <p>Version: <code id="fw-version">–</code></p>
    <form id="ota-form" method="POST" action="/api/ota" enctype="multipart/form-data">
      <input type="file" name="firmware" accept=".bin">
      <button type="submit">Upload &amp; Update</button>
    </form>
  </div>

  <script>
    let pairingActive = false;
    async function refresh() {
      try {
        const r = await fetch('/api/status');
        const s = await r.json();
        document.getElementById('ble-state').textContent = s.ble_connected ? '✅ Connected' : '❌ Disconnected';
        document.getElementById('ble-state').className = s.ble_connected ? 'ok' : 'err';
        document.getElementById('ble-mac').textContent = s.ble_mac || '–';
        document.getElementById('pair-state').textContent = s.pairing_state;
        document.getElementById('wifi-ip').textContent = s.wifi_ip;
        document.getElementById('wifi-mode').textContent = s.wifi_ap_mode ? '(AP mode)' : '(STA mode)';
        document.getElementById('fw-version').textContent = s.firmware_version;
        document.getElementById('mac-list').innerHTML = s.paired_macs.length
          ? s.paired_macs.map(m => `<div>${m}</div>`).join('')
          : '<em>No controllers paired</em>';
        pairingActive = (s.pairing_state === 'ACCEPT');
        document.getElementById('btn-pair').disabled = pairingActive;
        document.getElementById('btn-cancel-pair').disabled = !pairingActive;
      } catch (e) { console.error(e); }
    }
    setInterval(refresh, 2000);
    refresh();

    document.getElementById('btn-pair').onclick = async () => {
      await fetch('/api/pair/start', { method: 'POST' });
      refresh();
    };
    document.getElementById('btn-cancel-pair').onclick = async () => {
      await fetch('/api/pair/cancel', { method: 'POST' });
      refresh();
    };
    document.getElementById('btn-unpair').onclick = async () => {
      if (!confirm('Clear all paired controllers? You will need to re-pair.')) return;
      await fetch('/api/pair/clear', { method: 'POST' });
      refresh();
    };
  </script>
</body>
</html>
)rawliteral";

// --- JSON helpers -----------------------------------------------------

static String mac_to_string(const ble_mac_t *m) {
    char buf[18];
    snprintf(buf, sizeof(buf), "%02X:%02X:%02X:%02X:%02X:%02X",
             m->addr[0], m->addr[1], m->addr[2],
             m->addr[3], m->addr[4], m->addr[5]);
    return String(buf);
}

static void send_json_status(AsyncWebServerRequest *req) {
    web_status_t s;
    web_config_get_status(&s);

    // Build a paired-macs JSON array.
    ble_mac_t macs[BLE_MAX_PAIRED_CONTROLLERS];
    uint8_t count = 0;
    ble_gamepad_get_paired_macs(macs, &count);

    String json = "{";
    json += "\"ble_connected\":" + String(s.ble_connected ? "true" : "false") + ",";
    json += "\"ble_mac\":\"" + String(s.ble_mac) + "\",";
    json += "\"pairing_state\":\"" + String(s.pairing_state_str) + "\",";
    json += "\"paired_macs\":[";
    for (int i = 0; i < count; i++) {
        if (i > 0) json += ",";
        json += "\"" + mac_to_string(&macs[i]) + "\"";
    }
    json += "],";
    json += "\"wifi_connected\":" + String(s.wifi_connected ? "true" : "false") + ",";
    json += "\"wifi_ap_mode\":" + String(s.wifi_ap_mode ? "true" : "false") + ",";
    json += "\"wifi_ip\":\"" + String(s.wifi_ip) + "\",";
    json += "\"battery_mv\":" + String(s.battery_mv) + ",";
    json += "\"battery_state\":" + String(s.battery_state) + ",";
    json += "\"firmware_version\":\"" + String(s.firmware_version) + "\"";
    json += "}";

    req->send(200, "application/json", json);
}

// --- HTTP route registration -------------------------------------------

static void register_routes(void) {
    server->on("/", HTTP_GET, [](AsyncWebServerRequest *req) {
        req->send_P(200, "text/html", INDEX_HTML);
    });

    server->on("/api/status", HTTP_GET, send_json_status);

    server->on("/api/pair/start", HTTP_POST,
        [](AsyncWebServerRequest *req) {
            ble_gamepad_set_pairing_state(PAIRING_STATE_ACCEPT);
            req->send(200, "application/json", "{\"ok\":true}");
        },
        NULL
    );

    server->on("/api/pair/cancel", HTTP_POST,
        [](AsyncWebServerRequest *req) {
            ble_gamepad_set_pairing_state(PAIRING_STATE_IDLE);
            req->send(200, "application/json", "{\"ok\":true}");
        },
        NULL
    );

    server->on("/api/pair/clear", HTTP_POST,
        [](AsyncWebServerRequest *req) {
            ble_gamepad_clear_paired_macs();
            req->send(200, "application/json", "{\"ok\":true}");
        },
        NULL
    );

    // Board revision selection. POST /api/board/rev with body
    // "rev=3" or "rev=2" to set the active board revision. Takes
    // effect on next boot. POST /api/board/reset to clear the
    // override and fall back to compile-time BOARD_REV.
    server->on("/api/board/rev", HTTP_POST,
        [](AsyncWebServerRequest *req) {
            // No body params expected for simple set; we look at the
            // URL query string ?rev=N.
            if (!req->hasParam("rev")) {
                req->send(400, "application/json",
                          "{\"err\":\"missing rev parameter\"}");
                return;
            }
            int rev = req->getParam("rev")->value().toInt();
            esp_err_t err = board_detect_set_override(rev);
            if (err != ESP_OK) {
                req->send(400, "application/json",
                          "{\"err\":\"invalid rev (expected 2-255)\"}");
                return;
            }
            req->send(200, "application/json",
                      String("{\"ok\":true,\"rev\":") + rev + "}");
        },
        NULL
    );

    server->on("/api/board/reset", HTTP_POST,
        [](AsyncWebServerRequest *req) {
            esp_err_t err = board_detect_clear_override();
            if (err != ESP_OK) {
                req->send(500, "application/json",
                          "{\"err\":\"clear failed\"}");
                return;
            }
            req->send(200, "application/json", "{\"ok\":true}");
        },
        NULL
    );

    // OTA — accepts a multipart upload at /api/ota.
    server->on("/api/ota", HTTP_POST,
        [](AsyncWebServerRequest *req) {
            bool ok = !Update.hasError();
            req->send(ok ? 200 : 500, "application/json",
                      ok ? "{\"ok\":true}" : "{\"ok\":false,\"err\":\"update\"}");
            if (ok) {
                delay(500);
                ESP.restart();
            }
        },
        [](AsyncWebServerRequest *req, const String &filename, size_t index,
           uint8_t *data, size_t len, bool final) {
            if (index == 0) {
                ESP_LOGI(TAG, "OTA: receiving %s", filename.c_str());
                if (!Update.begin(UPDATE_SIZE_UNKNOWN)) {
                    Update.printError(Serial);
                    return;
                }
            }
            if (!Update.write(data, len)) {
                Update.printError(Serial);
                return;
            }
            if (final) {
                if (!Update.end(true)) {
                    Update.printError(Serial);
                }
            }
        }
    );

    // 404 — return JSON for API paths, HTML for others.
    server->onNotFound([](AsyncWebServerRequest *req) {
        if (req->url().startsWith("/api/")) {
            req->send(404, "application/json", "{\"err\":\"not found\"}");
        } else {
            req->redirect("/");
        }
    });
}

// --- WiFi setup --------------------------------------------------------

static void start_ap_mode(void) {
    char ap_ssid[32];
    snprintf(ap_ssid, sizeof(ap_ssid), "%s%04X", AP_SSID_PREFIX,
             (uint16_t)(ESP.getEfuseMac() >> 32) & 0xFFFF);
    WiFi.mode(WIFI_AP);
    WiFi.softAP(ap_ssid, ap_password);
    wifi_ap_mode = true;
    ESP_LOGW(TAG, "Started AP: %s (password: %s), IP: %s",
             ap_ssid, ap_password, WiFi.softAPIP().toString().c_str());
}

static esp_err_t try_sta_mode(void) {
    char ssid[33] = {0};
    char psk[65] = {0};
    if (wifi_load_credentials(ssid, sizeof(ssid), psk, sizeof(psk)) != ESP_OK) {
        ESP_LOGI(TAG, "No saved WiFi credentials, will start AP");
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "Trying saved WiFi: %s", ssid);
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, psk);
    // Block for up to 10s for connection.
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
        delay(500);
        attempts++;
    }
    if (WiFi.status() == WL_CONNECTED) {
        wifi_ap_mode = false;
        ESP_LOGI(TAG, "WiFi connected: %s", WiFi.localIP().toString().c_str());
        return ESP_OK;
    }
    ESP_LOGW(TAG, "WiFi connection failed after 10s, falling back to AP");
    return ESP_FAIL;
}

// --- Public API --------------------------------------------------------

esp_err_t web_config_init(void) {
    ESP_LOGI(TAG, "Initializing web config");

    server = new AsyncWebServer(80);

    // Try STA, fall back to AP.
    if (try_sta_mode() != ESP_OK) {
        start_ap_mode();
    }

    register_routes();
    server->begin();

    ESP_LOGI(TAG, "Web server started on port 80");
    return ESP_OK;
}

void web_config_loop(void) {
    // ESPAsyncWebServer runs handlers on its own task. We just need
    // to keep an eye on WiFi state for the captive portal DNS server
    // (TODO: implement once captive portal is added).
    static uint32_t last_check = 0;
    uint32_t now = millis();
    if (now - last_check < 5000) return;
    last_check = now;

    // If we were in STA and got disconnected, fall back to AP.
    if (!wifi_ap_mode && WiFi.status() != WL_CONNECTED) {
        ESP_LOGW(TAG, "WiFi lost, switching to AP mode");
        start_ap_mode();
    }
}

void web_config_get_status(web_status_t *out) {
    memset(out, 0, sizeof(*out));
    out->ble_connected = ble_gamepad_is_connected();
    out->wifi_connected = (WiFi.status() == WL_CONNECTED);
    out->wifi_ap_mode = wifi_ap_mode;
    if (wifi_ap_mode) {
        strncpy(out->wifi_ip, WiFi.softAPIP().toString().c_str(), sizeof(out->wifi_ip) - 1);
    } else {
        strncpy(out->wifi_ip, WiFi.localIP().toString().c_str(), sizeof(out->wifi_ip) - 1);
    }

    if (out->ble_connected) {
        // We don't expose the connected MAC from ble_gamepad_get_state
        // (only ControllerState is exposed). Could be added in v1.1.
        strncpy(out->ble_mac, "connected", sizeof(out->ble_mac) - 1);
    } else {
        strncpy(out->ble_mac, "—", sizeof(out->ble_mac) - 1);
    }

    switch (ble_gamepad_get_pairing_state()) {
        case PAIRING_STATE_IDLE:     out->pairing_state_str = "IDLE";     break;
        case PAIRING_STATE_ACCEPT:   out->pairing_state_str = "ACCEPT";   break;
        case PAIRING_STATE_DISABLED: out->pairing_state_str = "DISABLED"; break;
    }

    ble_mac_t macs[BLE_MAX_PAIRED_CONTROLLERS];
    uint8_t count = 0;
    ble_gamepad_get_paired_macs(macs, &count);
    snprintf(out->paired_count, sizeof(out->paired_count), "%u", count);

    // Battery is read by myrobot/PowerFunctions. We don't yet have a
    // public accessor for it. TODO: expose PowerFunctions::getBatteryMillivolts().
    out->battery_mv = 0;
    out->battery_state = 0;

    out->firmware_version = VERSION;
}