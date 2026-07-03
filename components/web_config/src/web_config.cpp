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
#include "output_config.h"
#include "Constants.h"

#include <Arduino.h>
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <AsyncTCP.h>
#include <Update.h>
#include <Preferences.h>
#include <DNSServer.h>
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
static AsyncWebSocket *ws = nullptr;
static DNSServer       dnsServer;     // captive-portal DNS, only active in AP mode
static bool wifi_ap_mode = false;
static char ap_password[32] = AP_DEFAULT_PASSWORD;

// Gamepad live state for the WebSocket streamer. Updated each loop tick
// when a client is connected.
static struct {
    bool connected;
    int  lx, ly, rx, ry, lt, rt;
    uint16_t buttons;
    uint16_t dpad;
    uint32_t last_send_ms;
    volatile bool broadcast_pending;
} s_gp = { false, 0, 0, 0, 0, 0, 0, 0, 0, 0, false };

// Connection callback registered with ble_gamepad. Notifies the WS loop
// that there's now something to broadcast.
static void gamepad_ws_event(AsyncWebSocket *server, AsyncWebSocketClient *client,
                             AwsEventType type, void *arg, uint8_t *data, size_t len);
static void gamepad_ws_broadcast_now(void);
static int gamepad_build_state_json(char *buf, size_t buflen);

static void on_ble_connection_change(bool connected, const ble_mac_t *mac) {
    s_gp.connected = connected;
    if (!connected) {
        // Reset sticks/triggers so the UI doesn't show stale values.
        s_gp.lx = s_gp.ly = s_gp.rx = s_gp.ry = 0;
        s_gp.lt = s_gp.rt = 0;
        s_gp.buttons = s_gp.dpad = 0;
    }
    // NimBLE invokes this callback from its own task. ESPAsyncWebServer /
    // AsyncTCP are not safe to call from here, so only mark the web loop
    // to broadcast on its next tick.
    s_gp.broadcast_pending = true;
}

// --- WebSocket live gamepad feed --------------------------------------

#define GAMEPAD_WS_PATH "/ws"
#define GAMEPAD_TICK_HZ 30

static void gamepad_ws_event(AsyncWebSocket *server, AsyncWebSocketClient *client,
                             AwsEventType type, void *arg, uint8_t *data, size_t len) {
    if (type == WS_EVT_CONNECT) {
        ESP_LOGI(TAG, "ws client #%u connected from %s", client->id(),
                 client->remoteIP().toString().c_str());
        if (Serial) {
            Serial.printf("[WS] client #%u connected count=%u\r\n",
                          client->id(), ws ? ws->count() : 0);
        }
        char buf[256];
        int n = gamepad_build_state_json(buf, sizeof(buf));
        if (n > 0) client->text(buf, n);
    } else if (type == WS_EVT_DISCONNECT) {
        ESP_LOGI(TAG, "ws client #%u disconnected", client->id());
        if (Serial) {
            Serial.printf("[WS] client #%u disconnected count=%u\r\n",
                          client->id(), ws ? ws->count() : 0);
        }
    }
}

// Build a JSON state message into buf and return the length. Pre-allocated
// 256-byte buffer is plenty for our 9-number state object. Pairing
// state is included so the page can show "ACCEPT" / "IDLE" without
// having to poll /api/status every second.
static int gamepad_build_state_json(char *buf, size_t buflen) {
    struct ControllerState cs = ble_gamepad_get_state();
    const char *pairing_str = "IDLE";
    switch (ble_gamepad_get_pairing_state()) {
        case PAIRING_STATE_IDLE:     pairing_str = "IDLE";     break;
        case PAIRING_STATE_ACCEPT:   pairing_str = "ACCEPT";   break;
        case PAIRING_STATE_DISABLED: pairing_str = "DISABLED"; break;
    }
    int n = snprintf(buf, buflen,
        "{\"type\":\"state\",\"connected\":%s,\"pairing\":\"%s\","
        "\"state\":{\"lx\":%d,\"ly\":%d,\"rx\":%d,\"ry\":%d,"
                  "\"lt\":%d,\"rt\":%d,"
                  "\"buttons\":%u,\"dpad\":%u}}",
        s_gp.connected ? "true" : "false",
        pairing_str,
        cs.leftStickX, cs.leftStickY, cs.rightStickX, cs.rightStickY,
        cs.leftTrigger, cs.rightTrigger,
        (unsigned)cs.buttons, (unsigned)cs.dpad);
    return (n > 0 && (size_t)n < buflen) ? n : -1;
}

// Broadcast a single state frame immediately to all WS clients (used
// right after a pairing-state change so the page reflects it without
// waiting up to 33ms for the next 30Hz tick).
static void gamepad_ws_broadcast_now(void) {
    if (!ws) return;
    uint32_t count = ws->count();
    if (count == 0) {
        if (Serial) Serial.printf("[WS] broadcast skipped count=0\r\n");
        return;
    }
    s_gp.last_send_ms = millis();
    char buf[256];
    int n = gamepad_build_state_json(buf, sizeof(buf));
    if (n < 0) return;
    if (Serial) Serial.printf("[WS] broadcast count=%u payload=%s\r\n", count, buf);
    ws->textAll(buf);
}

static void gamepad_ws_tick(void) {
    if (!ws) return;
    if (ws->count() == 0) {
        s_gp.broadcast_pending = false;
        return;
    }
    uint32_t now = millis();
    bool pending = s_gp.broadcast_pending;
    if (!pending && now - s_gp.last_send_ms < (1000 / GAMEPAD_TICK_HZ)) return;
    s_gp.broadcast_pending = false;
    s_gp.last_send_ms = now;

    char buf[256];
    int n = gamepad_build_state_json(buf, sizeof(buf));
    if (n < 0) return;
    ws->textAll(buf);
}

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
//
// The production HTML is generated from docs/config-ui-mockup.html by
// tools/gen_web_index.py into web_index_gen.h. That header is included
// here and supplies the canonical `INDEX_HTML[]` symbol.
#include "web_index_gen.h"

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

    // Output config (motor direction / servo type / input mapping).
    // Register the longer /api/config/sources path before /api/config;
    // ESPAsyncWebServer route matching can otherwise let the shorter
    // prefix handler consume /api/config/sources.
    server->on("/api/config/sources", HTTP_GET, [](AsyncWebServerRequest *req) {
        static char buf[OC_JSON_BUF_SIZE];
        int n = output_config_sources_to_json(buf, sizeof(buf));
        if (n < 0) {
            req->send(500, "application/json", "{\"err\":\"encode\"}");
            return;
        }
        AsyncWebServerResponse *resp = req->beginResponse(200, "application/json", buf);
        resp->addHeader("Cache-Control", "no-store");
        req->send(resp);
    });

    server->on("/api/config", HTTP_GET, [](AsyncWebServerRequest *req) {
        static char buf[OC_JSON_BUF_SIZE];
        int n = output_config_to_json(buf, sizeof(buf));
        if (n < 0) {
            req->send(500, "application/json", "{\"err\":\"encode\"}");
            return;
        }
        AsyncWebServerResponse *resp = req->beginResponse(200, "application/json", buf);
        resp->addHeader("Cache-Control", "no-store");
        req->send(resp);
    });

    server->on("/api/config", HTTP_PATCH, [](AsyncWebServerRequest *req) {
        // ESPAsyncWebServer doesn't give us a body for non-body methods
        // consistently. We accept the patch body via header or POST-style.
        // For now we require POST so the form data parser is engaged.
        req->send(405, "application/json", "{\"err\":\"use POST\"}");
    });

    // Buffer the body ourselves. The native "body handler" takes a
    // (uint8_t*, size_t) callback which is awkward for JSON; we collect
    // the body via Upload handler chunks (none expected for the JSON
    // PATCH) and read the raw request URI body via the request callback
    // when the request signals "body parsed".
    //
    // For ESPAsyncWebServer 3.6.0 the simplest contract that returns a
    // body to the server is a `body` handler with the proper signature.
    // The signature is:
    //   void body(AsyncWebServerRequest *req, uint8_t *data, size_t len,
    //             size_t index, size_t total)
    // We accumulate chunks and apply the patch in the final "request"
    // callback when index+len == total.
    server->on("/api/config", HTTP_POST,
        [](AsyncWebServerRequest *req) {
            // Fired after the request (including body) has been parsed.
            // We don't read the body here because the body-handler
            // below stashed it on the request's user context.
            auto *body = static_cast<String *>(req->_tempObject);
            if (!body) {
                req->send(400, "application/json", "{\"err\":\"no body\"}");
                return;
            }
            esp_err_t err = output_config_apply_json_patch(body->c_str());
            delete body;
            req->_tempObject = nullptr;
            if (err != ESP_OK) {
                req->send(400, "application/json", "{\"err\":\"invalid patch\"}");
                return;
            }
            req->send(200, "application/json", "{\"ok\":true}");
        },
        NULL,
        [](AsyncWebServerRequest *req, uint8_t *data, size_t len,
           size_t index, size_t total) {
            if (!req->_tempObject) {
                req->_tempObject = new String();
                static_cast<String *>(req->_tempObject)->reserve(total);
            }
            auto *body = static_cast<String *>(req->_tempObject);
            body->concat(reinterpret_cast<const char *>(data), len);
        });

    server->on("/api/pair/start", HTTP_POST,
        [](AsyncWebServerRequest *req) {
            ble_gamepad_set_pairing_state(PAIRING_STATE_ACCEPT);
            s_gp.broadcast_pending = true;
            req->send(200, "application/json", "{\"ok\":true}");
        },
        NULL
    );

    server->on("/api/pair/cancel", HTTP_POST,
        [](AsyncWebServerRequest *req) {
            ble_gamepad_set_pairing_state(PAIRING_STATE_IDLE);
            s_gp.broadcast_pending = true;
            req->send(200, "application/json", "{\"ok\":true}");
        },
        NULL
    );

    server->on("/api/pair/clear", HTTP_POST,
        [](AsyncWebServerRequest *req) {
            ble_gamepad_clear_paired_macs();
            s_gp.broadcast_pending = true;
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
    bool ok = WiFi.softAP(ap_ssid, ap_password);
    wifi_ap_mode = ok;
    ESP_LOGW(TAG, "Started AP: ok=%d ssid=%s ip=%s channel=%d stations=%d",
             (int)ok,
             ap_ssid,
             WiFi.softAPIP().toString().c_str(),
             WiFi.channel(),
             WiFi.softAPgetStationNum());
    if (Serial) {
        Serial.printf("[WIFI_AP] ok=%d ssid=%s ip=%s channel=%d stations=%d\r\n",
                      (int)ok,
                      ap_ssid,
                      WiFi.softAPIP().toString().c_str(),
                      WiFi.channel(),
                      WiFi.softAPgetStationNum());
    }

    // Captive-portal DNS: respond to every query with our AP IP, so clients
    // hitting "captive.apple.com", "connectivitycheck.gstatic.com", etc.
    // get redirected to our server. Combined with the onNotFound handler
    // above, any URL the user types resolves to /.
    dnsServer.stop();
    dnsServer.setErrorReplyCode(DNSReplyCode::NoError);
    dnsServer.start(53, "*", WiFi.softAPIP());
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

    // Output config must be initialized before we can serve /api/config.
    output_config_init();

    server = new AsyncWebServer(80);
    ws = new AsyncWebSocket(GAMEPAD_WS_PATH);
    ws->onEvent(gamepad_ws_event);
    server->addHandler(ws);

    // BLE gamepad connection callback so we know when to start streaming.
    ble_gamepad_set_connection_callback(on_ble_connection_change);

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
    // Drain captive-portal DNS requests whenever we're in AP mode.
    if (wifi_ap_mode) {
        dnsServer.processNextRequest();
    }

    // ESPAsyncWebServer runs handlers on its own task. We just need
    // to keep an eye on WiFi state for the captive portal DNS server
    // (TODO: implement once captive portal is added).
    static uint32_t last_check = 0;
    uint32_t now = millis();
    if (now - last_check < 5000) {
        gamepad_ws_tick();
        return;
    }
    last_check = now;

    // If we were in STA and got disconnected, fall back to AP.
    if (!wifi_ap_mode && WiFi.status() != WL_CONNECTED) {
        ESP_LOGW(TAG, "WiFi lost, switching to AP mode");
        start_ap_mode();
    }

    // Drain any dead WS clients so count() stays accurate.
    if (ws) ws->cleanupClients();
    gamepad_ws_tick();
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
