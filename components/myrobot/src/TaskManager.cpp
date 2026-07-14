
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
                    self->_leftTurnInput,     // leftStickX
                    self->_leftDriveInput,    // leftStickY
                    self->_rightTurnInput,    // rightStickX
                    self->_rightDriveInput,   // rightStickY
                    self->_forwardEscInput,   // rightTrigger
                    self->_reverseEscInput,   // leftTrigger
                    self->_buttonsInput,
                    self->_dpadInput,
                };

                const oc_drive_setup_t* driveSetup = output_config_get_drive_setup();
                const oc_output_cfg_t* m1Cfg = output_config_get(OC_OUT_M1);
                const oc_output_cfg_t* m2Cfg = output_config_get(OC_OUT_M2);
                self->drive.setMotorPwmFrequency(true, m1Cfg && m1Cfg->pwm_frequency_hz ? m1Cfg->pwm_frequency_hz : DRIVE_MOTOR_PWM_FREQ);
                self->drive.setMotorPwmFrequency(false, m2Cfg && m2Cfg->pwm_frequency_hz ? m2Cfg->pwm_frequency_hz : DRIVE_MOTOR_PWM_FREQ);
                self->_driveThrottle = 0;
                self->_driveSteering = 0;
                self->_driveLeftCommand = 0;
                self->_driveRightCommand = 0;
                if (driveSetup->method == OC_DRIVE_METHOD_NONE) {
                    const int16_t left = self->manualMotorCommand(OC_OUT_M1, m1Cfg, currentCs, true, driveLeftAllowed);
                    const int16_t right = self->manualMotorCommand(OC_OUT_M2, m2Cfg, currentCs, true, driveRightAllowed);
                    self->drive.single_motor_drive(true, left, self->currentOrientation, driveLeftAllowed);
                    self->drive.single_motor_drive(false, right, self->currentOrientation, driveRightAllowed);
                    self->_driveLeftCommand = left;
                    self->_driveRightCommand = right;
                } else if (driveLeftAllowed || driveRightAllowed) {
                    self->_m1Latched = false;
                    self->_m2Latched = false;
                    self->_m1PrevManualActive = false;
                    self->_m2PrevManualActive = false;
                    if (driveSetup->layout == OC_DRIVE_LAYOUT_SERVO_STEERING) {
                        int16_t throttle = self->readDriveAxis(driveSetup->throttle_axis, currentCs);
                        int16_t steering = self->readDriveAxis(driveSetup->steering_axis, currentCs);
                        throttle = self->applyDriveModifiersToThrottle(throttle, driveSetup, currentCs);
                        steering = self->applyDriveModifiersToSteering(steering, driveSetup, currentCs);
                        const bool useLeftMotor = driveSetup->drive_motor_output == OC_OUT_M1;
                        const oc_output_id_t motorId = useLeftMotor ? OC_OUT_M1 : OC_OUT_M2;
                        const oc_output_cfg_t* motorCfg = useLeftMotor ? m1Cfg : m2Cfg;
                        if (motorCfg->direction == OC_DIR_REVERSED) throttle = (int16_t)-throttle;
                        throttle = self->applyMotionRamp(motorId, throttle, motorCfg->ramp_ms, motorCfg->deceleration_ms);
                        throttle = self->applyPowerScale(motorId, throttle);
                        const bool allowed = useLeftMotor ? driveLeftAllowed : driveRightAllowed;
                        self->drive.single_motor_drive(useLeftMotor, throttle, self->currentOrientation, allowed);
                        if (useLeftMotor) self->drive.stopRight(); else self->drive.stopLeft();
                        self->updateSteeringServo(driveSetup->steering_output, steering, currentCs, true);
                        self->_driveThrottle = throttle;
                        self->_driveSteering = steering;
                        self->_driveLeftCommand = useLeftMotor ? throttle : 0;
                        self->_driveRightCommand = useLeftMotor ? 0 : throttle;
                    } else if (driveSetup->method == OC_DRIVE_METHOD_ARCADE) {
                        int16_t throttle = self->readDriveAxis(driveSetup->throttle_axis, currentCs);
                        int16_t steering = self->readDriveAxis(driveSetup->steering_axis, currentCs);
                        throttle = self->applyDriveModifiersToThrottle(throttle, driveSetup, currentCs);
                        steering = self->applyDriveModifiersToSteering(steering, driveSetup, currentCs);
                        // Preserve full yaw authority: as steering approaches full
                        // scale, suppress forward throttle rather than clipping one
                        // side and turning the robot into a slow pivot.
                        const int16_t drive = (int16_t)(((int32_t)throttle * (512 - abs(steering))) / 512);
                        int16_t left = constrain((int32_t)drive + steering, -512, 511);
                        int16_t right = constrain((int32_t)drive - steering, -512, 511);
                        left = (int16_t)(((int32_t)left * driveSetup->left_speed_pct) / 100);
                        right = (int16_t)(((int32_t)right * driveSetup->right_speed_pct) / 100);
                        const oc_output_cfg_t* leftCfg = output_config_get(OC_OUT_M1);
                        const oc_output_cfg_t* rightCfg = output_config_get(OC_OUT_M2);
                        if (leftCfg->direction == OC_DIR_REVERSED) left = (int16_t)-left;
                        if (rightCfg->direction == OC_DIR_REVERSED) right = (int16_t)-right;
                        left = self->applyMotionRamp(OC_OUT_M1, left, leftCfg->ramp_ms, leftCfg->deceleration_ms);
                        right = self->applyMotionRamp(OC_OUT_M2, right, rightCfg->ramp_ms, rightCfg->deceleration_ms);
                        left = self->applyPowerScale(OC_OUT_M1, left);
                        right = self->applyPowerScale(OC_OUT_M2, right);
                        self->drive.two_stick_drive(left, right, self->currentOrientation,
                                                    driveLeftAllowed, driveRightAllowed);
                        self->_driveThrottle = throttle;
                        self->_driveSteering = steering;
                        self->_driveLeftCommand = left;
                        self->_driveRightCommand = right;
                    } else {
                        int16_t left = self->readDriveAxis(driveSetup->left_axis, currentCs);
                        int16_t right = self->readDriveAxis(driveSetup->right_axis, currentCs);
                        left = self->applyDriveModifiersToThrottle(left, driveSetup, currentCs);
                        right = self->applyDriveModifiersToThrottle(right, driveSetup, currentCs);
                        left = (int16_t)(((int32_t)left * driveSetup->left_speed_pct) / 100);
                        right = (int16_t)(((int32_t)right * driveSetup->right_speed_pct) / 100);
                        const oc_output_cfg_t* leftCfg = output_config_get(OC_OUT_M1);
                        const oc_output_cfg_t* rightCfg = output_config_get(OC_OUT_M2);
                        if (leftCfg->direction == OC_DIR_REVERSED) left = (int16_t)-left;
                        if (rightCfg->direction == OC_DIR_REVERSED) right = (int16_t)-right;
                        left = self->applyMotionRamp(OC_OUT_M1, left, leftCfg->ramp_ms, leftCfg->deceleration_ms);
                        right = self->applyMotionRamp(OC_OUT_M2, right, rightCfg->ramp_ms, rightCfg->deceleration_ms);
                        left = self->applyPowerScale(OC_OUT_M1, left);
                        right = self->applyPowerScale(OC_OUT_M2, right);
                        self->drive.two_stick_drive(left, right, self->currentOrientation,
                                                    driveLeftAllowed, driveRightAllowed);
                        self->_driveLeftCommand = left;
                        self->_driveRightCommand = right;
                    }
                } else {
                    self->_m1Latched = false;
                    self->_m2Latched = false;
                    self->_m1PrevManualActive = false;
                    self->_m2PrevManualActive = false;
                    self->drive.stop();
                }

                if (!self->outputReservedForDriveSteering(OC_OUT_S1)) self->updateAuxOutput(OC_OUT_S1, PIN_SERVO1, self->_s1Pulse, currentCs, true);
                if (!self->outputReservedForDriveSteering(OC_OUT_S2)) self->updateAuxOutput(OC_OUT_S2, PIN_SERVO2, self->_s2Pulse, currentCs, true);
                self->motorsStopped = !(driveLeftAllowed || driveRightAllowed);
                //Put in things that can be updated even if voltage is low
                //Be careful not to put anything that could draw high current and could overdrain the battery
                //---------------------------------------------------------------
                self->adjustLedForBattery();


                //---------------------------------------------------------------

                
                self->lastUpdateTime = xTaskGetTickCount() * portTICK_PERIOD_MS;
            }
            else {
                if (!output_config_get_disconnect_failsafe_hold_last()) {
                    ControllerState emptyCs{0, 0, 0, 0, 0, 0, 0, 0};
                    self->updateAuxOutput(OC_OUT_S1, PIN_SERVO1, self->_s1Pulse, emptyCs, false);
                    self->updateAuxOutput(OC_OUT_S2, PIN_SERVO2, self->_s2Pulse, emptyCs, false);
                    self->_m1Latched = false; self->_m2Latched = false; self->_m1PrevManualActive = false; self->_m2PrevManualActive = false;
                    self->stopAllMotors();
                }
            }
            // clear the flag so we don't reapply next loop
            self->pendingUpdate = false;
        }

        //If we've timed out or lost connection, stop motors 
        if ((xTaskGetTickCount() * portTICK_PERIOD_MS - self->lastUpdateTime) >= self->_controllerTimeout ||
        self->_isConnected == false){
            if (!output_config_get_disconnect_failsafe_hold_last()) {
                ControllerState emptyCs{0, 0, 0, 0, 0, 0, 0, 0};
                self->updateAuxOutput(OC_OUT_S1, PIN_SERVO1, self->_s1Pulse, emptyCs, false);
                self->updateAuxOutput(OC_OUT_S2, PIN_SERVO2, self->_s2Pulse, emptyCs, false);
                self->_m1Latched = false; self->_m2Latched = false; self->_m1PrevManualActive = false; self->_m2PrevManualActive = false;
                self->stopAllMotors();
            }
            self->ledStrip.setColor(0, 0, 255, 0);        // Blue LEDs indicate the controller has timed out
        } 


        const oc_sw1_config_t* sw1Cfg = output_config_get_sw1_config();
        self->buttons.setHoldTimeMs(sw1Cfg ? sw1Cfg->hold_ms : 5000);
        ButtonPress buttonVal = self->buttons.checkForPress();
  
        switch(buttonVal){
            case BUTTON_NONE:
            break;

            case BUTTON_SHORT: {
            ESP_LOGI(TAG,"Button: Short Press");
            self->handleSw1Action(sw1Cfg ? sw1Cfg->short_action : OC_SW1_ACTION_PAIRING);
            }
                
            break;

            case BUTTON_DOUBLE: {
            ESP_LOGI(TAG,"Button: Double Press");
            self->handleSw1Action(sw1Cfg ? sw1Cfg->double_action : OC_SW1_ACTION_NONE);
            }
            break;

            case BUTTON_LONG:
            ESP_LOGI(TAG,"Button: Long Press");
            self->led.enqueuePattern(".-.", false, 255);
            break;

            case BUTTON_HOLD_5S: {
            ESP_LOGI(TAG, "Button: configured hold action");
            self->handleSw1Action(sw1Cfg ? sw1Cfg->hold_action : OC_SW1_ACTION_CLEAR_PAIR);
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
    _precisionLatched = false;
    _precisionPrevPressed = false;
    for (unsigned i = 0; i < OC_OUT__COUNT; ++i) {
        _rampedOutput[i] = 0;
        _rampUpdatedMs[i] = 0;
    }
}

void TaskManager::handleSw1Action(oc_sw1_action_t action){
    switch (action) {
        case OC_SW1_ACTION_NONE:
            break;
        case OC_SW1_ACTION_PAIRING:
            ble_gamepad_set_pairing_state(PAIRING_STATE_ACCEPT);
            break;
        case OC_SW1_ACTION_CLEAR_PAIR:
            ble_gamepad_clear_paired_macs();
            break;
        case OC_SW1_ACTION_CANCEL_PAIRING:
            ble_gamepad_set_pairing_state(PAIRING_STATE_IDLE);
            break;
        case OC_SW1_ACTION_RESET_OUTPUTS:
            output_config_reset_defaults();
            output_config_commit();
            break;
        case OC_SW1_ACTION_BATTERY_STATUS:
            led.enqueuePattern(batteryState == BATTERY_LOW ? "..." : (batteryState == BATTERY_WARN ? ".-." : "-"), false, 255);
            break;
        default:
            break;
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

int16_t TaskManager::getDriveThrottle() const { return _driveThrottle; }
int16_t TaskManager::getDriveSteering() const { return _driveSteering; }
int16_t TaskManager::getDriveLeftCommand() const { return _driveLeftCommand; }
int16_t TaskManager::getDriveRightCommand() const { return _driveRightCommand; }

DriveMotorIntent TaskManager::getMotorIntent(oc_output_id_t id) const {
    return drive.getMotorIntent(id != OC_OUT_M2);
}

const char* TaskManager::getOutputBlockedReason(oc_output_id_t id) const {
    const oc_output_cfg_t* cfg = output_config_get(id);
    if (!cfg || cfg->purpose == OC_PURPOSE_DISABLED ||
        ((id == OC_OUT_M1 || id == OC_OUT_M2) && cfg->motor_mode == OC_MOTOR_MODE_DISABLED)) return "disabled";
    if (!output_config_channel_allowed(id, PowerFunctions::getLastBatteryState())) return "low_battery";
    if (!_isConnected) return "disconnect";
    if ((id == OC_OUT_S1 || id == OC_OUT_S2) && cfg->purpose == OC_PURPOSE_ESC) {
        const char* phase = getEscArmPhaseName(id);
        if (strcmp(phase, "armed") != 0 && strcmp(phase, "manual") != 0) return "arming";
    }
    if (cfg->weapon_safety && cfg->deadman_source >= OC_SRC_BTN_A && cfg->deadman_source <= OC_SRC_BTN_HOME) {
        uint16_t mask = (uint16_t)(1u << (cfg->deadman_source - OC_SRC_BTN_A));
        if ((_buttonsInput & mask) == 0) return "deadman";
    }
    if ((id == OC_OUT_S1 || id == OC_OUT_S2) && cfg->primary == OC_SRC_NONE &&
        cfg->purpose != OC_PURPOSE_PWM_ACCESSORY && cfg->purpose != OC_PURPOSE_RGB_LIGHTING) return "no_source";
    return "none";
}

static int16_t map_trigger_pair_to_axis(int16_t forward, int16_t reverse) {
    int32_t diff = (int32_t)forward - (int32_t)reverse;
    if (diff == 0) return 0;
    diff = constrain(diff, -1023, 1023);
    return (int16_t)map(diff, -1023, 1023, -512, 511);
}

static int16_t map_trigger_one_way_to_axis(int16_t trigger) {
    int32_t v = constrain((int32_t)trigger, 0, 1023);
    return (int16_t)map(v, 0, 1023, 0, 511);
}

int16_t TaskManager::readDriveAxis(oc_drive_axis_t axis, const ControllerState& cs) const {
    switch (axis) {
        case OC_DRIVE_AXIS_LY: return (int16_t)cs.leftStickY;
        case OC_DRIVE_AXIS_RY: return (int16_t)cs.rightStickY;
        case OC_DRIVE_AXIS_LX: return (int16_t)cs.leftStickX;
        case OC_DRIVE_AXIS_RX: return (int16_t)cs.rightStickX;
        case OC_DRIVE_AXIS_RT_MINUS_LT: return map_trigger_pair_to_axis(cs.rightTrigger, cs.leftTrigger);
        case OC_DRIVE_AXIS_LT_MINUS_RT: return map_trigger_pair_to_axis(cs.leftTrigger, cs.rightTrigger);
        case OC_DRIVE_AXIS_RT_ONLY: return map_trigger_one_way_to_axis(cs.rightTrigger);
        case OC_DRIVE_AXIS_LT_ONLY: return map_trigger_one_way_to_axis(cs.leftTrigger);
        case OC_DRIVE_AXIS_DPAD_Y:
            return ((cs.dpad & 0x01) ? 511 : 0) + ((cs.dpad & 0x02) ? -512 : 0);
        case OC_DRIVE_AXIS_DPAD_X:
            return ((cs.dpad & 0x08) ? 511 : 0) + ((cs.dpad & 0x04) ? -512 : 0);
        case OC_DRIVE_AXIS_NONE:
        default: return 0;
    }
}

bool TaskManager::driveModifierActive(oc_source_id_t src, const ControllerState& cs) const {
    return src != OC_SRC_NONE && readConfigSource(src, cs) != 0;
}

bool TaskManager::precisionModifierActive(const oc_drive_setup_t* setup, const ControllerState& cs) {
    if (!setup || setup->precision_source == OC_SRC_NONE) {
        _precisionLatched = false;
        _precisionPrevPressed = false;
        return false;
    }
    bool pressed = driveModifierActive(setup->precision_source, cs);
    if (!setup->precision_latching) {
        _precisionPrevPressed = pressed;
        return pressed;
    }
    if (pressed && !_precisionPrevPressed) _precisionLatched = !_precisionLatched;
    _precisionPrevPressed = pressed;
    return _precisionLatched;
}

int16_t TaskManager::applyDriveModifiersToThrottle(int16_t throttle, const oc_drive_setup_t* setup, const ControllerState& cs) {
    if (!setup) return throttle;
    if (driveModifierActive(setup->brake_source, cs)) return 0;
    if (precisionModifierActive(setup, cs)) {
        throttle = (int16_t)((int32_t)throttle * setup->precision_scale_pct / 100);
    }
    return throttle;
}

int16_t TaskManager::applyDriveModifiersToSteering(int16_t steering, const oc_drive_setup_t* setup, const ControllerState& cs) {
    if (!setup) return steering;
    if (driveModifierActive(setup->brake_source, cs)) return 0;
    if (precisionModifierActive(setup, cs)) {
        steering = (int16_t)((int32_t)steering * setup->precision_scale_pct / 100);
    }
    if (driveModifierActive(setup->invert_steering_source, cs)) steering = (int16_t)-steering;
    return steering;
}

int16_t TaskManager::applyPowerScale(oc_output_id_t id, int16_t value) const {
    if (ENABLE_LOW_BATTERY_SHUTDOWN &&
        output_config_channel_power_action(id, (uint8_t)batteryState) == OC_POWER_REDUCE) {
        value = (int16_t)((int32_t)value * 50 / 100);
    }
    return constrain(value, -512, 511);
}

uint16_t TaskManager::applyPowerScaleUnsigned(oc_output_id_t id, uint16_t value) const {
    if (ENABLE_LOW_BATTERY_SHUTDOWN &&
        output_config_channel_power_action(id, (uint8_t)batteryState) == OC_POWER_REDUCE) {
        value = (uint16_t)((uint32_t)value * 50 / 100);
    }
    return value;
}

int16_t TaskManager::applyMotionRamp(oc_output_id_t id, int16_t target, uint16_t accelerationMs, uint16_t decelerationMs) {
    if ((unsigned)id >= OC_OUT__COUNT) return target;
    const uint32_t now = millis();
    uint32_t& last = _rampUpdatedMs[id];
    int16_t& current = _rampedOutput[id];
    if (last == 0) last = now;
    if (accelerationMs == 0 && decelerationMs == 0) {
        current = target;
        return current;
    }
    const uint32_t elapsed = max((uint32_t)1, now - last);
    last = now;
    // A sign reversal must decelerate through zero before accelerating away.
    int16_t effectiveTarget = target;
    bool reversing = current != 0 && target != 0 && ((current < 0) != (target < 0));
    if (reversing) effectiveTarget = 0;
    bool accelerating = !reversing && abs(effectiveTarget) > abs(current);
    uint16_t duration = accelerating ? accelerationMs : decelerationMs;
    if (duration == 0) current = effectiveTarget;
    else {
        int32_t step = max((int32_t)1, (int32_t)(512u * elapsed / duration));
        const oc_output_cfg_t* cfg = output_config_get(id);
        if (cfg && cfg->ramp_curve == OC_RAMP_S_CURVE && cfg->ramp_smoothing_pct > 0) {
            // Bell-shaped velocity: gentle at both ends and fastest near mid-travel.
            float progress = min(1.0f, (float)abs(current) / 512.0f);
            float curveFactor = 0.30f + 1.40f * (4.0f * progress * (1.0f - progress));
            float blend = (float)cfg->ramp_smoothing_pct / 100.0f;
            step = max((int32_t)1, (int32_t)(step * ((1.0f - blend) + blend * curveFactor)));
        }
        if (effectiveTarget > current) current = (int16_t)min((int32_t)effectiveTarget, (int32_t)current + step);
        else if (effectiveTarget < current) current = (int16_t)max((int32_t)effectiveTarget, (int32_t)current - step);
    }
    return current;
}

bool TaskManager::outputReservedForDriveSteering(oc_output_id_t id) const {
    const oc_drive_setup_t* setup = output_config_get_drive_setup();
    return setup && setup->layout == OC_DRIVE_LAYOUT_SERVO_STEERING && setup->steering_output == id;
}

void TaskManager::updateSteeringServo(oc_output_id_t id, int16_t steering, const ControllerState& cs, bool connected) {
    if (id != OC_OUT_S1 && id != OC_OUT_S2) return;
    PulseOutput& pulse = (id == OC_OUT_S1) ? _s1Pulse : _s2Pulse;
    const oc_output_cfg_t* cfg = output_config_get(id);
    PulseProtocol protocol = protocolFromConfig(cfg);
    pulse.begin(protocol);
    if (!connected) {
        pulse.safeState(PULSE_ESC_BIDIRECTIONAL);
        return;
    }
    int16_t value = cfg && cfg->direction == OC_DIR_REVERSED ? (int16_t)-steering : steering;
    value = applyMotionRamp(id, value, cfg->ramp_ms, cfg->deceleration_ms);
    value = applyPowerScale(id, value);
    value = constrain(value, -512, 511);
    uint16_t pulseUs;
    if (cfg && cfg->servo_mode == OC_SERVO_UNI) {
        uint16_t magnitude = (uint16_t)constrain(value > 0 ? value : 0, 0, 511);
        pulseUs = pulse_output_map_range(magnitude, 0, 511, protocol.center_us, protocol.max_us);
    } else if (value >= 0) {
        pulseUs = pulse_output_map_range((uint16_t)value, 0, 511, protocol.center_us, protocol.max_us);
    } else {
        pulseUs = pulse_output_map_range((uint16_t)(-value), 0, 512, protocol.center_us, protocol.min_us);
    }
    pulse.writePulseUs(pulseUs);
}

bool TaskManager::manualMotorSourceActive(const oc_output_cfg_t* cfg, const ControllerState& cs) const {
    if (!cfg || cfg->primary == OC_SRC_NONE) return false;
    return readConfigSourceMagnitude(cfg->primary, cs) > 0;
}

int16_t TaskManager::manualMotorCommand(oc_output_id_t id, const oc_output_cfg_t* cfg, const ControllerState& cs, bool connected, bool allowed) {
    if (!cfg || !connected || !allowed || cfg->motor_mode == OC_MOTOR_MODE_DISABLED) {
        if (id == OC_OUT_M1) { _m1Latched = false; _m1PrevManualActive = false; }
        if (id == OC_OUT_M2) { _m2Latched = false; _m2PrevManualActive = false; }
        return 0;
    }

    int16_t command = 0;
    const bool active = manualMotorSourceActive(cfg, cs);
    const int16_t fixed = (int16_t)map((long)constrain((int)cfg->pwm_duty_pct, 0, 100), 0, 100, 0, 511);

    switch (cfg->motor_mode) {
        case OC_MOTOR_MODE_PROPORTIONAL: {
            if (cfg->primary == OC_SRC_LT || cfg->primary == OC_SRC_RT) {
                command = (int16_t)map((long)readConfigSourceMagnitude(cfg->primary, cs), 0, 1023, 0, 511);
            } else {
                command = constrain(readConfigSource(cfg->primary, cs), -512, 511);
            }
            break;
        }
        case OC_MOTOR_MODE_MOMENTARY:
            command = active ? fixed : 0;
            break;
        case OC_MOTOR_MODE_LATCHING: {
            bool& latched = (id == OC_OUT_M1) ? _m1Latched : _m2Latched;
            bool& prev = (id == OC_OUT_M1) ? _m1PrevManualActive : _m2PrevManualActive;
            if (active && !prev) latched = !latched;
            prev = active;
            command = latched ? fixed : 0;
            break;
        }
        case OC_MOTOR_MODE_DISABLED:
        default:
            command = 0;
            break;
    }

    if (cfg->direction == OC_DIR_REVERSED) command = -command;
    command = applyMotionRamp(id, command, cfg->ramp_ms, cfg->deceleration_ms);
    command = applyPowerScale(id, command);
    return constrain(command, -512, 511);
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
    switch (cfg->protocol) {
        case OC_PROTO_RC_SERVO_PWM:
        case OC_PROTO_RC_SERVO_PPM:
            protocol = PULSE_PROTOCOL_RC_SERVO_PWM;
            break;
        case OC_PROTO_RC_SERVO_PWM_100:
            protocol = PULSE_PROTOCOL_RC_SERVO_PWM_100;
            break;
        case OC_PROTO_RC_SERVO_PWM_200:
            protocol = PULSE_PROTOCOL_RC_SERVO_PWM_200;
            break;
        case OC_PROTO_RC_SERVO_PWM_333:
            protocol = PULSE_PROTOCOL_RC_SERVO_PWM_333;
            break;
        case OC_PROTO_RC_ESC_PWM:
            protocol = PULSE_PROTOCOL_RC_ESC_PWM;
            break;
        case OC_PROTO_RC_ESC_PWM_100:
            protocol = PULSE_PROTOCOL_RC_ESC_PWM_100;
            break;
        case OC_PROTO_RC_ESC_PWM_250:
            protocol = PULSE_PROTOCOL_RC_ESC_PWM_250;
            break;
        case OC_PROTO_RC_ESC_PWM_333:
            protocol = PULSE_PROTOCOL_RC_ESC_PWM_333;
            break;
        case OC_PROTO_RC_ESC_PWM_490:
            protocol = PULSE_PROTOCOL_RC_ESC_PWM_490;
            break;
        case OC_PROTO_ONESHOT:
            protocol = PULSE_PROTOCOL_ONESHOT;
            break;
        case OC_PROTO_ONESHOT125:
            protocol = PULSE_PROTOCOL_ONESHOT125;
            break;
        case OC_PROTO_ONESHOT42:
            protocol = PULSE_PROTOCOL_ONESHOT42;
            break;
        case OC_PROTO_MULTISHOT:
            protocol = PULSE_PROTOCOL_MULTISHOT;
            break;
        default:
            break;
    }
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
    if (cfg->purpose == OC_PURPOSE_RGB_LIGHTING &&
        (cfg->protocol == OC_PROTO_RGB || cfg->protocol == OC_PROTO_RGBW)) {
        // RGB/RGBW lighting is a first-class S1/S2 configuration role.
        // Current S1/S2 firmware does not bit-bang addressable LEDs through
        // the servo PWM path, so keep the signal pin safe/low rather than
        // emitting servo pulses on a configured lighting channel.
        pinMode(pin, OUTPUT);
        digitalWrite(pin, LOW);
        if (id == OC_OUT_S1) { _s1DigitalLogical = false; _s1DigitalPhysicalHigh = false; }
        if (id == OC_OUT_S2) { _s2DigitalLogical = false; _s2DigitalPhysicalHigh = false; }
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
        uint16_t pulseUs;
        if (cfg->servo_mode == OC_SERVO_BI) {
            int16_t value = constrain(readConfigSource(cfg->primary, cs), -512, 511);
            if (cfg->direction == OC_DIR_REVERSED) value = -value;
            value = applyMotionRamp(id, value, cfg->ramp_ms, cfg->deceleration_ms);
            value = applyPowerScale(id, value);
            pulseUs = pulse_output_map_range((uint16_t)(value + 512), 0, 1023, protocol.min_us, protocol.max_us);
        } else {
            uint16_t input = applyPowerScaleUnsigned(id, readConfigSourceMagnitude(cfg->primary, cs));
            int16_t ramped = applyMotionRamp(id, (int16_t)(input / 2), cfg->ramp_ms, cfg->deceleration_ms);
            pulseUs = pulse_output_map_range((uint16_t)constrain(ramped * 2, 0, 1023), 0, 1023, protocol.min_us, protocol.max_us);
        }
        pulse.writePulseUs(pulseUs);
        return;
    }

    uint16_t forward = applyPowerScaleUnsigned(id, readConfigSourceMagnitude(cfg->primary, cs));
    uint16_t reverse = applyPowerScaleUnsigned(id, readConfigSourceMagnitude(cfg->secondary, cs));
    int16_t target = (int16_t)constrain(((int32_t)forward - (int32_t)reverse) / 2, -512, 511);
    int16_t ramped = applyMotionRamp(id, target, cfg->ramp_ms, cfg->deceleration_ms);
    pulse.writeEsc((uint16_t)max(0, (int)ramped * 2),
                   (uint16_t)max(0, (int)-ramped * 2), semantics);
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