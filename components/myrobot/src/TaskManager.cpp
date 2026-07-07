
#include <TaskManager.h>
#include <Arduino.h>
#include <Constants.h>
#include <Drive.h>
#include <PowerFunctions.h>
#include <Buttons.h>
#include "ble_gamepad.h"
#include "esp_log.h"
#include "LED.h"
#include "rgbLED.h"
#include "output_config.h"
#include "board_config.h"
#include <Adafruit_NeoPixel.h>
#include "esp_pm.h"


#include "esp_task_wdt.h"



static const char* TAG = "TaskManager";

TaskManager::TaskManager()
  : _s1Pulse(PIN_SERVO1, SERVO1_PWM_CHANNEL, AUX_PWM_RESOLUTION),
    _s2Pulse(PIN_SERVO2, SERVO2_PWM_CHANNEL, AUX_PWM_RESOLUTION),
    buttons(MODE_BUTTON_PIN),
    led(DEBUG_LED_PIN),
    ledStrip(4, ESC_2_PIN, NEO_GRBW + NEO_KHZ800),
    _isConnected(false),
    _leftDriveInput(0),
    _rightDriveInput(0),
    _leftTurnInput(0),
    _rightTurnInput(0),
    _forwardEscInput(0),
    _reverseEscInput(0),
    _buttonsInput(0),
    _dpadInput(0),
    lastUpdateTime(0),
    _controllerTimeout(CONTROLLER_TIMEOUT),
    motorsStopped(true),
    pendingUpdate(false),
    taskHandle(nullptr)
{}

void TaskManager::begin(){


    output_config_init();
    pinMode(PIN_SERVO1, OUTPUT);
    pinMode(PIN_SERVO2, OUTPUT);
    digitalWrite(PIN_SERVO1, LOW);
    digitalWrite(PIN_SERVO2, LOW);

    drive.begin();
    drive.setForwardInputLimits(511,-512);
    drive.setLateralInputLimits(-512,511);

    _s1Pulse.begin(PULSE_PROTOCOL_RC_SERVO_PWM);
    _s2Pulse.begin(PULSE_PROTOCOL_RC_SERVO_PWM);
    _s1Pulse.setInputLimits(0,1023);
    _s2Pulse.setInputLimits(0,1023);

    powerFunctions.begin();

    buttons.begin();

    led.begin();

    //vTaskDelay(pdMS_TO_TICKS(100));

    esp_pm_lock_handle_t pm_lock;
    esp_pm_lock_create(ESP_PM_NO_LIGHT_SLEEP, 0, "no_light_sleep", &pm_lock);
    esp_pm_lock_acquire(pm_lock);


    ledStrip.begin();
    ledStrip.setBrightness(255);
    ledStrip.setColor(255, 0, 0, 0);


    // create the RTOS task (adjust stack if you overflow)
    // Stack size bumped 4096 -> 6144 (2026-07-04): managerTask calls into
    // combined_direction / two_stick_drive / adjustLedForBattery (which
    // allocates the rainbow color buffer) under one stack frame, which
    // left no headroom against the ESP32-C3's stack-overflow canary. With
    // CONFIG_ARDUINO_RUNNING_CORE set to 1 (single-core) and FreeRTOS
    // configUSE_STACK_OVERFLOW_CHECK enabled, a 4096-byte stack can fire
    // the canary under sustained rainbow animation.
    xTaskCreatePinnedToCore(
        managerTask,           // function
        "TaskManager",         // name
        6144,                  // stack size in bytes
        this,                  // pvParameters
        tskIDLE_PRIORITY + 1,  // priority
        &taskHandle,           // handle
        APP_CPU_NUM            // core
    );
}

void TaskManager::managerTask(void* pvParameters) {
    auto* self = static_cast<TaskManager*>(pvParameters);
    TickType_t lastWake = xTaskGetTickCount();
    const TickType_t period = pdMS_TO_TICKS(50);  // adjust as needed

    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));

    for (;;) {

        vTaskDelayUntil(&lastWake, period);

        self->batteryState = self->powerFunctions.getBatteryState();
        
        //If there's a new controller update pending, apply it
        if (self->pendingUpdate) {
            if (self->_isConnected) {
                const bool driveLeftAllowed = !ENABLE_LOW_BATTERY_SHUTDOWN ||
                    output_config_channel_allowed(OC_OUT_M1, self->batteryState);
                const bool driveRightAllowed = !ENABLE_LOW_BATTERY_SHUTDOWN ||
                    output_config_channel_allowed(OC_OUT_M2, self->batteryState);
                ControllerState currentCs{
                    self->_leftTurnInput,
                    self->_leftDriveInput,
                    self->_rightTurnInput,
                    self->_rightDriveInput,
                    self->_forwardEscInput,
                    self->_reverseEscInput,
                    self->_buttonsInput,
                    self->_dpadInput,
                };

                if (driveLeftAllowed || driveRightAllowed) {
                    switch(output_config_get_drive_mode()) {
                        case OC_DRIVE_ARCADE_LEFT:
                            self->drive.combined_direction(self->_leftTurnInput, self->_leftDriveInput, self->currentOrientation,
                                                           driveLeftAllowed, driveRightAllowed);
                            break;
                        case OC_DRIVE_ARCADE_RIGHT:
                            self->drive.combined_direction(self->_rightTurnInput, self->_rightDriveInput, self->currentOrientation,
                                                           driveLeftAllowed, driveRightAllowed);
                            break;
                        case OC_DRIVE_ARCADE_SPLIT:
                            self->drive.combined_direction(self->_rightTurnInput, self->_leftDriveInput, self->currentOrientation,
                                                           driveLeftAllowed, driveRightAllowed);
                            break;
                        case OC_DRIVE_TANK_SPLIT:
                        default:
                            self->drive.two_stick_drive(self->_leftDriveInput, self->_rightDriveInput, self->currentOrientation,
                                                        driveLeftAllowed, driveRightAllowed);
                            break;
                    }
                } else {
                    self->drive.stop();
                }

                self->updateAuxOutput(OC_OUT_S1, PIN_SERVO1, self->_s1Pulse, currentCs, true);
                self->updateAuxOutput(OC_OUT_S2, PIN_SERVO2, self->_s2Pulse, currentCs, true);
                self->motorsStopped = !(driveLeftAllowed || driveRightAllowed);
                //Put in things that can be updated even if voltage is low
                //Be careful not to put anything that could draw high current and could overdrain the battery
                //---------------------------------------------------------------
                self->adjustLedForBattery();


                //---------------------------------------------------------------

                
                self->lastUpdateTime = xTaskGetTickCount() * portTICK_PERIOD_MS;
            }
            else {
                ControllerState emptyCs{0, 0, 0, 0, 0, 0, 0, 0};
                self->updateAuxOutput(OC_OUT_S1, PIN_SERVO1, self->_s1Pulse, emptyCs, false);
                self->updateAuxOutput(OC_OUT_S2, PIN_SERVO2, self->_s2Pulse, emptyCs, false);
                self->stopAllMotors();
            }
            // clear the flag so we don't reapply next loop
            self->pendingUpdate = false;
        }

        //If we've timed out or lost connection, stop motors 
        if ((xTaskGetTickCount() * portTICK_PERIOD_MS - self->lastUpdateTime) >= self->_controllerTimeout ||
        self->_isConnected == false){
            ControllerState emptyCs{0, 0, 0, 0, 0, 0, 0, 0};
            self->updateAuxOutput(OC_OUT_S1, PIN_SERVO1, self->_s1Pulse, emptyCs, false);
            self->updateAuxOutput(OC_OUT_S2, PIN_SERVO2, self->_s2Pulse, emptyCs, false);
            self->stopAllMotors();
            self->ledStrip.setColor(0, 0, 255, 0);        // Blue LEDs indicate the controller has timed out
        } 


        ButtonPress buttonVal = self->buttons.checkForPress();
  
        switch(buttonVal){
            case BUTTON_NONE:
            break;

            case BUTTON_SHORT: {
            ESP_LOGI(TAG,"Button: Short Press");
            self->led.enqueuePattern("---", false, 255);
            }
                
            break;

            case BUTTON_LONG:
            ESP_LOGI(TAG,"Button: Long Press");
            self->led.enqueuePattern(".-.", false, 255);
            break;

            case BUTTON_HOLD_5S: {
            // SW1 held for >= 5 seconds. Clear the whitelist (which
            // disconnects the active controller and ends by entering
            // pairing) so a fresh controller can be paired. The
            // existing LED1 indicator task and HTML/WS auto-reflect
            // are already wired to react to that state transition.
            ESP_LOGI(TAG, "Button: Hold 5s — clear whitelist and pair");
            ble_gamepad_clear_paired_macs();
            }
            break;

            default:
            break;
        }

        ESP_ERROR_CHECK(esp_task_wdt_reset());   // feed for THIS task
    }
}


/**
 * Update the task manager with recent controller values
 * @param isConnected         Is the controller actively connected
 * @param ControllerState     Pass the values of the controller inputs
 *    
 */
void TaskManager::update(bool isConnected, const ControllerState& cs){
    _isConnected = isConnected;
    _leftDriveInput   = cs.leftStickY;
    _rightDriveInput  = cs.rightStickY;
    _leftTurnInput    = cs.leftStickX;
    _rightTurnInput   = cs.rightStickX;
    _forwardEscInput  = cs.rightTrigger;
    _reverseEscInput  = cs.leftTrigger;
    _buttonsInput     = cs.buttons;
    _dpadInput        = cs.dpad;
    processButtons(cs);
    pendingUpdate     = true;
}

//Stop all motors in the robot. If everything is already stopped, it will pass
void TaskManager::stopAllMotors(){
    if(motorsStopped == false){
        ESP_LOGI(TAG, "Stopping Motors");
        drive.stop();
        _s1Pulse.safeState(PULSE_ESC_BIDIRECTIONAL);
        _s2Pulse.safeState(PULSE_ESC_BIDIRECTIONAL);
        motorsStopped = true;
    }
}

void TaskManager::processButtons(const ControllerState& cs){
    static bool prevA = 0, prevB = 0, prevX = 0, prevY = 0;

    bool A = (cs.buttons >> 0) & 0x01;
    bool B = (cs.buttons >> 1) & 0x01;
    bool X = (cs.buttons >> 2) & 0x01;
    bool Y = (cs.buttons >> 3) & 0x01;

    if( prevY == 0 && Y == 1){
        flipOrientation();
    }

    prevA = A;
    prevB = B;
    prevX = X;
    prevY = Y;
}


void TaskManager::flipOrientation(){
    if( currentOrientation == RIGHTSIDE_UP ){
        currentOrientation = UPSIDE_DOWN;
    }
    else{
        currentOrientation = RIGHTSIDE_UP;
    }
}

bool TaskManager::getDigitalOutputLogical(oc_output_id_t id) const {
    if (id == OC_OUT_S1) return _s1DigitalLogical;
    if (id == OC_OUT_S2) return _s2DigitalLogical;
    return false;
}

bool TaskManager::getDigitalOutputPhysicalHigh(oc_output_id_t id) const {
    if (id == OC_OUT_S1) return _s1DigitalPhysicalHigh;
    if (id == OC_OUT_S2) return _s2DigitalPhysicalHigh;
    return false;
}

uint16_t TaskManager::getAuxPulseUs(oc_output_id_t id) const {
    if (id == OC_OUT_S1) return _s1Pulse.lastPulseUs();
    if (id == OC_OUT_S2) return _s2Pulse.lastPulseUs();
    return 0;
}

uint16_t TaskManager::getAuxDuty(oc_output_id_t id) const {
    if (id == OC_OUT_S1) return _s1Pulse.lastDuty();
    if (id == OC_OUT_S2) return _s2Pulse.lastDuty();
    return 0;
}

const char* TaskManager::getEscArmPhaseName(oc_output_id_t id) const {
    const EscArmState& st = (id == OC_OUT_S1) ? _s1EscArm : _s2EscArm;
    switch (st.phase) {
        case ESC_ARM_PHASE_MANUAL: return "manual";
        case ESC_ARM_PHASE_WAITING: return "waiting";
        case ESC_ARM_PHASE_HOLDING: return "holding";
        case ESC_ARM_PHASE_LOW1: return "low1";
        case ESC_ARM_PHASE_HIGH: return "high";
        case ESC_ARM_PHASE_LOW2: return "low2";
        case ESC_ARM_PHASE_ARMED: return "armed";
        case ESC_ARM_PHASE_INACTIVE:
        default: return "inactive";
    }
}

int16_t TaskManager::readConfigSource(oc_source_id_t src, const ControllerState& cs) const {
    switch (src) {
        case OC_SRC_LX: return (int16_t)cs.leftStickX;
        case OC_SRC_LY: return (int16_t)cs.leftStickY;
        case OC_SRC_RX: return (int16_t)cs.rightStickX;
        case OC_SRC_RY: return (int16_t)cs.rightStickY;
        case OC_SRC_LT: return (int16_t)cs.leftTrigger;
        case OC_SRC_RT: return (int16_t)cs.rightTrigger;
        case OC_SRC_BTN_A: return (cs.buttons & (1u << 0)) ? 1 : 0;
        case OC_SRC_BTN_B: return (cs.buttons & (1u << 1)) ? 1 : 0;
        case OC_SRC_BTN_X: return (cs.buttons & (1u << 2)) ? 1 : 0;
        case OC_SRC_BTN_Y: return (cs.buttons & (1u << 3)) ? 1 : 0;
        case OC_SRC_BTN_L1: return (cs.buttons & (1u << 4)) ? 1 : 0;
        case OC_SRC_BTN_R1: return (cs.buttons & (1u << 5)) ? 1 : 0;
        case OC_SRC_BTN_L2: return (cs.buttons & (1u << 6)) ? 1 : 0;
        case OC_SRC_BTN_R2: return (cs.buttons & (1u << 7)) ? 1 : 0;
        case OC_SRC_BTN_SELECT: return (cs.buttons & (1u << 8)) ? 1 : 0;
        case OC_SRC_BTN_START: return (cs.buttons & (1u << 9)) ? 1 : 0;
        case OC_SRC_BTN_L3: return (cs.buttons & (1u << 10)) ? 1 : 0;
        case OC_SRC_BTN_R3: return (cs.buttons & (1u << 11)) ? 1 : 0;
        case OC_SRC_BTN_HOME: return (cs.buttons & (1u << 12)) ? 1 : 0;
        case OC_SRC_DPAD_UP: return (cs.dpad & 0x01) ? 1 : 0;
        case OC_SRC_DPAD_DOWN: return (cs.dpad & 0x02) ? 1 : 0;
        case OC_SRC_DPAD_LEFT: return (cs.dpad & 0x04) ? 1 : 0;
        case OC_SRC_DPAD_RIGHT: return (cs.dpad & 0x08) ? 1 : 0;
        case OC_SRC_NONE:
        default: return 0;
    }
}

bool TaskManager::evaluateDigitalOutput(const oc_output_cfg_t* cfg, const ControllerState& cs, bool previousState) const {
    if (!cfg || cfg->primary == OC_SRC_NONE) return cfg ? cfg->default_state : false;
    int16_t value = readConfigSource(cfg->primary, cs);
    switch (cfg->digital_mode) {
        case OC_DIGITAL_MODE_DIRECT:
            return value != 0;
        case OC_DIGITAL_MODE_ANALOG_ABOVE:
            if (value >= cfg->digital_on_threshold) return true;
            if (value <= cfg->digital_off_threshold) return false;
            return previousState;
        case OC_DIGITAL_MODE_ANALOG_BELOW:
            if (value <= cfg->digital_on_threshold) return true;
            if (value >= cfg->digital_off_threshold) return false;
            return previousState;
        default:
            return cfg->default_state;
    }
}


uint16_t TaskManager::readConfigSourceMagnitude(oc_source_id_t src, const ControllerState& cs) const {
    int16_t value = readConfigSource(src, cs);
    switch (src) {
        case OC_SRC_LT:
        case OC_SRC_RT:
            return (uint16_t)constrain(value, 0, 1023);
        case OC_SRC_LX:
        case OC_SRC_LY:
        case OC_SRC_RX:
        case OC_SRC_RY:
            return (uint16_t)constrain(abs(value) * 2, 0, 1023);
        case OC_SRC_NONE:
            return 0;
        default:
            return value ? 1023 : 0;
    }
}

PulseProtocol TaskManager::protocolFromConfig(const oc_output_cfg_t* cfg) const {
    PulseProtocol protocol = PULSE_PROTOCOL_RC_SERVO_PWM;
    if (!cfg) return protocol;
    if (cfg->protocol == OC_PROTO_ONESHOT125) protocol = PULSE_PROTOCOL_ONESHOT125;
    else if (cfg->protocol == OC_PROTO_RC_ESC_PWM) protocol = PULSE_PROTOCOL_RC_ESC_PWM;
    else if (cfg->protocol == OC_PROTO_RC_SERVO_PWM || cfg->protocol == OC_PROTO_RC_SERVO_PPM) protocol = PULSE_PROTOCOL_RC_SERVO_PWM;
    if (cfg->frame_hz) protocol.frame_hz = cfg->frame_hz;
    if (cfg->min_pulse_us && cfg->center_pulse_us && cfg->max_pulse_us) {
        protocol.min_us = cfg->min_pulse_us;
        protocol.center_us = cfg->center_pulse_us;
        protocol.max_us = cfg->max_pulse_us;
    }
    return protocol;
}

PulseEscSemantics TaskManager::escSemanticsFromConfig(const oc_output_cfg_t* cfg) const {
    return cfg && cfg->semantics == OC_SEM_ESC_BIDIRECTIONAL
        ? PULSE_ESC_BIDIRECTIONAL
        : PULSE_ESC_FORWARD_ONLY;
}

bool TaskManager::updateEscArming(oc_output_id_t id, PulseOutput& pulse, const oc_output_cfg_t* cfg, const ControllerState& cs, const PulseProtocol& protocol) {
    if (!cfg) return true;
    EscArmState& st = (id == OC_OUT_S1) ? _s1EscArm : _s2EscArm;
    if (cfg->purpose != OC_PURPOSE_ESC) {
        st.armed = false;
        st.sequence_running = false;
        st.phase = ESC_ARM_PHASE_INACTIVE;
        return true;
    }
    const uint32_t signature = ((uint32_t)cfg->esc_arm_mode << 28) ^
        ((uint32_t)cfg->protocol << 24) ^ ((uint32_t)cfg->esc_arm_source << 16) ^
        ((uint32_t)cfg->esc_arm_low_us << 1) ^ ((uint32_t)cfg->esc_arm_high_us << 12) ^
        ((uint32_t)cfg->esc_arm_low_ms << 3) ^ ((uint32_t)cfg->esc_arm_high_ms << 5) ^
        ((uint32_t)cfg->esc_arm_final_low_ms << 7) ^ cfg->esc_arm_hold_ms;
    if (st.signature != signature) {
        st = EscArmState{};
        st.signature = signature;
    }
    if (cfg->esc_arm_mode == OC_ESC_ARM_MANUAL) {
        st.armed = true;
        st.sequence_running = false;
        st.phase = ESC_ARM_PHASE_MANUAL;
        return true;
    }

    const uint32_t now = millis();
    if (!st.armed && !st.sequence_running) {
        if (cfg->esc_arm_mode == OC_ESC_ARM_BOOT) {
            st.sequence_running = true;
            st.sequence_started_ms = now;
            st.phase = ESC_ARM_PHASE_LOW1;
        } else if (cfg->esc_arm_mode == OC_ESC_ARM_HOLD_SOURCE) {
            const bool held = cfg->esc_arm_source != OC_SRC_NONE && readConfigSource(cfg->esc_arm_source, cs) != 0;
            if (!held) {
                st.hold_started_ms = 0;
                st.phase = ESC_ARM_PHASE_WAITING;
                pulse.writePulseUs(cfg->esc_arm_low_us);
                return false;
            }
            if (st.hold_started_ms == 0) st.hold_started_ms = now;
            if ((uint32_t)(now - st.hold_started_ms) >= cfg->esc_arm_hold_ms) {
                st.sequence_running = true;
                st.sequence_started_ms = now;
                st.phase = ESC_ARM_PHASE_LOW1;
            } else {
                st.phase = ESC_ARM_PHASE_HOLDING;
                pulse.writePulseUs(cfg->esc_arm_low_us);
                return false;
            }
        }
    }

    if (st.sequence_running) {
        const uint32_t elapsed = now - st.sequence_started_ms;
        const uint32_t low1_end = cfg->esc_arm_low_ms;
        const uint32_t high_end = low1_end + cfg->esc_arm_high_ms;
        const uint32_t low2_end = high_end + cfg->esc_arm_final_low_ms;
        if (elapsed < low1_end) {
            st.phase = ESC_ARM_PHASE_LOW1;
            pulse.writePulseUs(cfg->esc_arm_low_us);
            return false;
        }
        if (elapsed < high_end) {
            st.phase = ESC_ARM_PHASE_HIGH;
            pulse.writePulseUs(cfg->esc_arm_high_us);
            return false;
        }
        if (elapsed < low2_end) {
            st.phase = ESC_ARM_PHASE_LOW2;
            pulse.writePulseUs(cfg->esc_arm_low_us);
            return false;
        }
        st.sequence_running = false;
        st.armed = true;
        st.phase = ESC_ARM_PHASE_ARMED;
    }
    return st.armed;
}

bool TaskManager::weaponRoleArmed(const oc_output_cfg_t* cfg, const ControllerState& cs) const {
    if (!cfg || !cfg->weapon_safety) return true;
    switch (cfg->weapon_mode) {
        case OC_WEAPON_BENCH_OVERRIDE:
            return true;
        case OC_WEAPON_DEADMAN_ONLY:
            return cfg->deadman_source != OC_SRC_NONE && readConfigSource(cfg->deadman_source, cs) != 0;
        case OC_WEAPON_ARMING_AND_DEADMAN:
        default:
            return cfg->arming_source != OC_SRC_NONE && cfg->deadman_source != OC_SRC_NONE &&
                   readConfigSource(cfg->arming_source, cs) != 0 &&
                   readConfigSource(cfg->deadman_source, cs) != 0;
    }
}

void TaskManager::updateAuxOutput(oc_output_id_t id, uint8_t pin, PulseOutput& pulse, const ControllerState& cs, bool connected) {
    const oc_output_cfg_t* cfg = output_config_get(id);
    if (!cfg) return;
    if (cfg->purpose == OC_PURPOSE_DIGITAL_OUTPUT && cfg->protocol == OC_PROTO_GPIO) {
        updateDigitalOutput(id, pin, cs, connected);
        return;
    }
    if (cfg->purpose == OC_PURPOSE_SERVO || cfg->purpose == OC_PURPOSE_ESC) {
        updatePulseOutput(id, pulse, cs, connected);
        return;
    }
    if (cfg->purpose == OC_PURPOSE_DIGITAL_INPUT) {
        pinMode(pin, cfg->active_high ? INPUT_PULLDOWN : INPUT_PULLUP);
        return;
    }
    if (cfg->purpose == OC_PURPOSE_DISABLED) {
        pinMode(pin, OUTPUT);
        digitalWrite(pin, cfg->default_state ? HIGH : LOW);
    }
}

void TaskManager::updatePulseOutput(oc_output_id_t id, PulseOutput& pulse, const ControllerState& cs, bool connected) {
    const oc_output_cfg_t* cfg = output_config_get(id);
    if (!cfg) return;
    const PulseProtocol protocol = protocolFromConfig(cfg);
    pulse.configure(protocol);
    ledcChangeFrequency(id == OC_OUT_S1 ? SERVO1_PWM_CHANNEL : SERVO2_PWM_CHANNEL, protocol.frame_hz, AUX_PWM_RESOLUTION);

    const bool channelAllowed = !ENABLE_LOW_BATTERY_SHUTDOWN || output_config_channel_allowed(id, batteryState);
    const bool escArmed = updateEscArming(id, pulse, cfg, cs, protocol);
    if (!escArmed) {
        return;
    }
    const bool roleAllowed = connected && channelAllowed && weaponRoleArmed(cfg, cs) && cfg->primary != OC_SRC_NONE;
    const PulseEscSemantics semantics = escSemanticsFromConfig(cfg);
    if (!roleAllowed) {
        pulse.safeState(semantics);
        return;
    }

    if (cfg->purpose == OC_PURPOSE_SERVO) {
        uint16_t input = readConfigSourceMagnitude(cfg->primary, cs);
        uint16_t pulseUs = pulse_output_map_range(input, 0, 1023, protocol.min_us, protocol.max_us);
        pulse.writePulseUs(pulseUs);
        return;
    }

    uint16_t forward = readConfigSourceMagnitude(cfg->primary, cs);
    uint16_t reverse = readConfigSourceMagnitude(cfg->secondary, cs);
    pulse.writeEsc(forward, reverse, semantics);
}

void TaskManager::updateDigitalOutput(oc_output_id_t id, uint8_t pin, const ControllerState& cs, bool connected) {
    const oc_output_cfg_t* cfg = output_config_get(id);
    if (!cfg || cfg->purpose != OC_PURPOSE_DIGITAL_OUTPUT || cfg->protocol != OC_PROTO_GPIO) {
        return;
    }

    bool previous = getDigitalOutputLogical(id);
    bool logical = evaluateDigitalOutput(cfg, cs, previous);
    if (!connected || cfg->primary == OC_SRC_NONE) {
        logical = cfg->default_state;
    }
    if (ENABLE_LOW_BATTERY_SHUTDOWN && !output_config_channel_allowed(id, batteryState)) {
        logical = cfg->default_state;
    }

    bool physicalHigh = cfg->active_high ? logical : !logical;
    pinMode(pin, OUTPUT);
    digitalWrite(pin, physicalHigh ? HIGH : LOW);

    if (id == OC_OUT_S1) {
        _s1DigitalLogical = logical;
        _s1DigitalPhysicalHigh = physicalHigh;
    } else if (id == OC_OUT_S2) {
        _s2DigitalLogical = logical;
        _s2DigitalPhysicalHigh = physicalHigh;
    }
}

void TaskManager::adjustLedForBattery(){

    // Battery-state check and update LED/accessory indication. Per-channel
    // motor/weapon cutoff is handled in managerTask via output_config_channel_allowed().
    // Treat the onboard strip/accessory as tied to the servo/accessory headers for now,
    // so setting either S1 or S2 LOW=disable can turn the accessory off at low voltage.
    if (ENABLE_LOW_BATTERY_SHUTDOWN &&
        (!output_config_channel_allowed(OC_OUT_S1, batteryState) ||
         !output_config_channel_allowed(OC_OUT_S2, batteryState))) {
        ledStrip.setColor(0, 0, 0, 0);
        return;
    }

    static int lastBatteryState = -1;
    
    if(lastBatteryState != batteryState || true){ //Only update if there is a change in the battery state from last time
        switch (batteryState) {
            case BATTERY_GOOD:
                ledStrip.setRainbow(true, 20, 25);   // effect for "good"
                break;

            case BATTERY_WARN:
                ledStrip.setColor(255, 255, 0, 0);      // yellow
                break;

            case BATTERY_LOW:
                ledStrip.setColor(255, 0, 0, 0);        // red
                break;
            default:
                ledStrip.setColor(255, 0, 0, 0);        // red
                break;
        }
    }

    lastBatteryState = batteryState;
}