// sketch.cpp — Arduino setup() / loop() for combat robot v2.
//
// Replaces v1.3 Bluepad32 integration. Now:
//   * Reads gamepad state from ble_gamepad (NimBLE-backed)
//   * Feeds myrobot/TaskManager exactly the same way v1.3 did
//   * Polls the pairing button (MODE_BUTTON_PIN) to cycle states
//   * Initializes web_config (when implemented) for the HTML UI
//
// SPDX-License-Identifier: Apache-2.0

#include "sdkconfig.h"

#include <Arduino.h>
#include <WiFi.h>
#include <stdarg.h>
#include <stdio.h>
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "esp_pm.h"
#include "nvs_flash.h"
#include "esp_event.h"
#include "esp_netif.h"

#include "Constants.h"
#include "TaskManager.h"

#include "ble_gamepad.h"
#include "web_config.h"

static const char *TAG = "Main";

static void boot_trace(const char *msg) {
    if (Serial) {
        Serial.printf("[BOOT %lu] %s\r\n", (unsigned long)millis(), msg);
    }
    ESP_LOGI(TAG, "%s", msg);
}

static void boot_tracef(const char *fmt, ...) {
    char buf[160];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    boot_trace(buf);
}

ControllerState controllerState;   // shared with myrobot/TaskManager

TaskManager taskManager;

// --- Pairing mode button ----------------------------------------------
//
// The MODE_BUTTON_PIN (GPIO5 on C3) is already used by Buttons.cpp for
// short/long press events driving TaskManager. We layer pairing-mode
// toggles on top:
//   - Single short press: cycle to next pairing state
//     (IDLE -> ACCEPT -> IDLE)
//   - Long press (>3s) in ACCEPT mode: clear whitelist + stay in ACCEPT
//
// Note: in v1.3 this was driven by the Arduino loop. We keep that
// pattern; web UI can also drive the same state via the public API.

static void handle_pairing_button(void) {
    // NOTE: this hook point will be wired into the existing Buttons
    // class once we finalize the button event surface. For the first
    // cut, we leave the API surface (ble_gamepad_set_pairing_state)
    // ready and let the web UI drive pairing.
    //
    // Implementation deferred to LATER: see docs/TESTING.md.
}

// --- LED1 pairing indicator --------------------------------------------
//
// LED1 (DEBUG_LED_PIN) is the v2 board's standard LED, wired to the LED
// class in TaskManager for morse-code patterns. That class can't be
// driven from the NimBLE pairing callback because the LED's pattern
// task only knows about enqueuePattern(). For the simple binary
// "pairing / connected / idle" indicator we want here, driving the pin
// directly is cleaner. Behavior:
//   * PAIRING_STATE_ACCEPT  : 250ms on / 250ms off blink
//   * controller connected : solid ON
//   * otherwise            : OFF
// The pairing state machine drives ACCEPT <-> IDLE, and the existing
// on_ble_connection_change callback in web_config mirrors the
// connected state. We watch both at 20ms cadence to keep the LED
// output stable against rapid re-entry into pairing.

static volatile bool g_pairing_led_active = false;
static volatile bool g_connected_led_active = false;
static TaskHandle_t g_led1_task = nullptr;
static portMUX_TYPE g_led1_lock = portMUX_INITIALIZER_UNLOCKED;

static void led1_indicator_task(void *pvParameters) {
    (void)pvParameters;
    pinMode(DEBUG_LED_PIN, OUTPUT);
    digitalWrite(DEBUG_LED_PIN, LOW);
    bool on = false;
    TickType_t last = xTaskGetTickCount();
    for (;;) {
        bool pairing;
        bool connected;
        portENTER_CRITICAL(&g_led1_lock);
        pairing = g_pairing_led_active;
        connected = g_connected_led_active;
        portEXIT_CRITICAL(&g_led1_lock);

        if (pairing) {
            // 250ms on / 250ms off. Half-period tick is 250ms; we flip
            // the LED each tick, so duty = 50%.
            TickType_t now = xTaskGetTickCount();
            if (now - last >= pdMS_TO_TICKS(250)) {
                last = now;
                on = !on;
                digitalWrite(DEBUG_LED_PIN, on ? HIGH : LOW);
            }
        } else {
            // Reset the phase so the next entry into pairing always
            // starts on a clean 250ms tick.
            on = true;
            last = xTaskGetTickCount();
            digitalWrite(DEBUG_LED_PIN, connected ? HIGH : LOW);
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

static void on_pairing_state_change(PairingState state) {
    portENTER_CRITICAL(&g_led1_lock);
    g_pairing_led_active = (state == PAIRING_STATE_ACCEPT);
    portEXIT_CRITICAL(&g_led1_lock);
}

// Called from the existing on_ble_connection_change path in
// web_config via a thin shim. The shim lives in this TU so the
// web_config component does not have to know about LED1.
// Exposed as a C symbol with C linkage so the web_config archive
// can resolve the reference during the static-library link pass
// (it is compiled before sketch.cpp). The body in this TU is the
// real implementation; a weak fallback also lives in web_config
// so non-sketch builds still link.
extern "C" void main_notify_connected(bool connected) {
    portENTER_CRITICAL(&g_led1_lock);
    g_connected_led_active = connected;
    portEXIT_CRITICAL(&g_led1_lock);
}

// --- Connection state callback ----------------------------------------
//
// ble_gamepad fires on_ble_connection_change on every connect/disconnect.
// There is no per-TU callback chain yet, so the *single* registration
// site is web_config_init() in components/web_config/src/web_config.cpp
// (which sets s_gp.broadcast_pending and logs connect/disconnect). If
// you need to add additional handlers here, extend
// ble_gamepad_set_connection_callback to support a list, then register
// each listener from its own TU.

// --- Arduino lifecycle ------------------------------------------------

void setup() {
    Serial.begin(115200);
    Serial.setDebugOutput(true);
    delay(300);
    boot_trace("setup begin");

    // Disable automatic light sleep (matches v1.3 behavior; required
    // because RMT (NeoPixel) doesn't coexist with light sleep on C3).
    esp_pm_lock_handle_t pm_lock;
    boot_trace("pm lock create");
    esp_pm_lock_create(ESP_PM_NO_LIGHT_SLEEP, 0, "no_light_sleep", &pm_lock);
    esp_pm_lock_acquire(pm_lock);
    boot_trace("pm lock acquired");

    // Verbose logging for development; drop to INFO for production.
    esp_log_level_set("*", ESP_LOG_INFO);

    boot_tracef("Robot Firmware: %s", VERSION);
    boot_trace("BLE stack: NimBLE (replaces Bluepad32)");

    // NVS must be initialized before any component that uses it.
    // ble_gamepad uses NVS for the MAC whitelist; web_config uses it
    // for WiFi credentials.
    boot_trace("nvs init begin");
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        boot_tracef("nvs init requested erase: 0x%x", (unsigned)err);
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    if (err != ESP_OK) boot_tracef("nvs init failed: 0x%x", (unsigned)err);
    ESP_ERROR_CHECK(err);
    boot_trace("nvs init ok");

    // TCP/IP stack and event loop are needed for WiFi (used by web_config).
    boot_trace("netif init begin");
    err = esp_netif_init();
    if (err != ESP_OK) boot_tracef("netif init failed: 0x%x", (unsigned)err);
    ESP_ERROR_CHECK(err);
    boot_trace("netif init ok");

    boot_trace("event loop create begin");
    err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) boot_tracef("event loop create failed: 0x%x", (unsigned)err);
    if (err != ESP_ERR_INVALID_STATE) ESP_ERROR_CHECK(err);
    boot_trace("event loop create ok");

    // Initialize BLE gamepad parser. Does not start scanning yet —
    // that happens on nimble host sync.
    boot_trace("ble_gamepad_init begin");
    err = ble_gamepad_init();
    if (err != ESP_OK) boot_tracef("ble_gamepad_init failed: 0x%x", (unsigned)err);
    ESP_ERROR_CHECK(err);
    boot_trace("ble_gamepad_init ok");

    // Register the BLE connection-state callback before the web UI starts.
    // Do not start active BLE scanning yet: ESP32-C3 WiFi and BLE share the
    // 2.4GHz radio, and starting a continuous scan before softAP setup can
    // make the config AP hard to see or associate with.
    // NOTE: ble_gamepad_set_connection_callback is registered by web_config_init
    // (later in setup()) because web_config is the only consumer of the
    // broadcast_pending flag. The connection log lines that used to live here
    // were moved into web_config's callback so we keep a single registration site.
    boot_trace("ble callback deferred to web_config_init");

    // Initialize myrobot subsystems (motors, drum, LEDs, battery, etc.).
    boot_trace("taskManager.begin begin");
    taskManager.begin();
    boot_trace("taskManager.begin ok");

    // Web config — WiFi + async HTTP server + HTML UI.
    // Must come after nvs_flash_init() and esp_netif_init() above.
    // WiFi.begin() may take ~10s if it has to try saved credentials;
    // runs synchronously inside init() to make connection state
    // predictable.
    boot_trace("web_config_init begin");
    err = web_config_init();
    if (err != ESP_OK) boot_tracef("web_config_init failed: 0x%x", (unsigned)err);
    ESP_ERROR_CHECK(err);
    boot_trace("web_config_init ok");

    // Now that the AP/server is initialized, start BLE scanning/bench
    // advertising. This ordering keeps the robot config UI reachable while
    // pairing scans are active.
    boot_trace("ble_gamepad_start begin");
    err = ble_gamepad_start();
    if (err != ESP_OK) boot_tracef("ble_gamepad_start failed: 0x%x", (unsigned)err);
    ESP_ERROR_CHECK(err);
    boot_trace("ble_gamepad_start ok");

    // LED1 pairing-indicator task and the BLE pairing callback. Must be
    // registered after ble_gamepad_start() so the subsystem is live.
    if (g_led1_task == nullptr) {
        xTaskCreatePinnedToCore(
            led1_indicator_task, "led1_pair", 2048, nullptr,
            tskIDLE_PRIORITY + 1, &g_led1_task, APP_CPU_NUM);
    }
    ble_gamepad_set_pairing_callback(on_pairing_state_change);

    // Watchdog: same pattern as v1.3.
    boot_trace("watchdog add begin");
    err = esp_task_wdt_add(NULL);
    if (err != ESP_OK) boot_tracef("watchdog add failed: 0x%x", (unsigned)err);
    ESP_ERROR_CHECK(err);
    boot_trace("setup done");

    // TODO (Phase 2): handle_pairing_button() integration with Buttons class.
}

void loop() {
    // Read the latest gamepad state from ble_gamepad and feed TaskManager.
    // This replaces v1.3's BP32.update() + processControllers() flow but
    // produces the same ControllerState structure.
    ControllerState gs = ble_gamepad_get_state();

    if (ble_gamepad_is_connected()) {
        controllerState.leftStickY    = gs.leftStickY;
        controllerState.rightStickY   = gs.rightStickY;
        controllerState.rightTrigger  = gs.rightTrigger;
        controllerState.leftTrigger   = gs.leftTrigger;
        controllerState.buttons       = gs.buttons;
        controllerState.dpad          = gs.dpad;
        taskManager.update(true, controllerState);
    } else {
        controllerState.leftStickY    = 0;
        controllerState.rightStickY   = 0;
        controllerState.rightTrigger  = 0;
        controllerState.leftTrigger   = 0;
        controllerState.buttons       = 0;
        controllerState.dpad          = 0;
        taskManager.update(false, controllerState);
    }

    handle_pairing_button();
    ble_gamepad_poll();

    // Service the web_config (WiFi watchdog, future captive portal DNS).
    web_config_loop();

    static uint32_t last_heartbeat_ms = 0;
    uint32_t now = millis();
    if (now - last_heartbeat_ms >= 5000) {
        last_heartbeat_ms = now;
        if (Serial) {
            Serial.printf("[HEARTBEAT %lu] wifi_mode=%d ap_ip=%s sta_ip=%s stations=%d ble_connected=%d pairing=%d\r\n",
                          (unsigned long)now,
                          (int)WiFi.getMode(),
                          WiFi.softAPIP().toString().c_str(),
                          WiFi.localIP().toString().c_str(),
                          WiFi.softAPgetStationNum(),
                          ble_gamepad_is_connected() ? 1 : 0,
                          (int)ble_gamepad_get_pairing_state());
        }
    }

    // Feed the watchdog.
    esp_task_wdt_reset();

    // Same 10Hz cadence as v1.3. See docs/DECISIONS.md L5 — could be
    // tightened to 50Hz for more responsive combat driving.
    vTaskDelay(pdMS_TO_TICKS(100));
}
