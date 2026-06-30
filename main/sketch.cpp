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
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "esp_pm.h"

#include "Constants.h"
#include "TaskManager.h"

#include "ble_gamepad.h"
#include "web_config.h"

static const char *TAG = "Main";

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

// --- Connection state callback ----------------------------------------
//
// ble_gamepad fires this on every connect/disconnect. We use it to
// update the LED strip (rainbow when paired/connected, red blinking
// when not, green pulse when pairing).

static void on_ble_connection_change(bool connected, const ble_mac_t *mac) {
    if (connected) {
        ESP_LOGI(TAG, "BLE controller connected: %02x:%02x:%02x:%02x:%02x:%02x",
                 mac->addr[0], mac->addr[1], mac->addr[2],
                 mac->addr[3], mac->addr[4], mac->addr[5]);
    } else {
        ESP_LOGI(TAG, "BLE controller disconnected");
    }
    // LED feedback handled inside TaskManager.managerTask via
    // adjustLedForBattery(). A future enhancement could add a
    // "pairing state" LED mode here.
}

// --- Arduino lifecycle ------------------------------------------------

void setup() {
    // Disable automatic light sleep (matches v1.3 behavior; required
    // because RMT (NeoPixel) doesn't coexist with light sleep on C3).
    esp_pm_lock_handle_t pm_lock;
    esp_pm_lock_create(ESP_PM_NO_LIGHT_SLEEP, 0, "no_light_sleep", &pm_lock);
    esp_pm_lock_acquire(pm_lock);

    // Verbose logging for development; drop to INFO for production.
    esp_log_level_set("*", ESP_LOG_INFO);

    ESP_LOGI(TAG, "Robot Firmware: %s", VERSION);
    ESP_LOGI(TAG, "BLE stack: NimBLE (replaces Bluepad32)");

    // Register the BLE connection-state callback.
    ble_gamepad_set_connection_callback(on_ble_connection_change);

    // Initialize myrobot subsystems (motors, drum, LEDs, battery, etc.).
    taskManager.begin();

    // Web config — WiFi + async HTTP server + HTML UI.
    // Must come after nvs_flash_init() (in main.c) and esp_netif_init()
    // (in main.c). WiFi.begin() may take ~10s if it has to try saved
    // credentials; runs synchronously inside init() to make connection
    // state predictable.
    ESP_ERROR_CHECK(web_config_init());

    // Watchdog: same pattern as v1.3.
    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));

    // TODO (Phase 2): handle_pairing_button() integration with Buttons class.
}

void loop() {
    // Read the latest gamepad state from ble_gamepad and feed TaskManager.
    // This replaces v1.3's BP32.update() + processControllers() flow but
    // produces the same ControllerState structure.
    ControllerState gs = ble_gamepad_get_state();

    if (gs.connected) {
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

    // Service the web_config (WiFi watchdog, future captive portal DNS).
    web_config_loop();

    // Feed the watchdog.
    esp_task_wdt_reset();

    // Same 10Hz cadence as v1.3. See docs/DECISIONS.md L5 — could be
    // tightened to 50Hz for more responsive combat driving.
    vTaskDelay(pdMS_TO_TICKS(100));
}