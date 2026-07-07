#ifndef TASKMANAGER_H
#define TASKMANAGER_H

#include <Arduino.h>
#include "Constants.h"
#include "PulseOutput.h"
#include "Drive.h"
#include "PowerFunctions.h"
#include "Buttons.h"
#include "LED.h"
#include "rgbLED.h"
#include "output_config.h"
#include "esp_pm.h"

// FreeRTOS
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

class TaskManager {
public:
    TaskManager();
    void begin();
    void update(bool isConnected, const ControllerState& cs);
    void stopAllMotors();
    void flipOrientation();
    bool getDigitalOutputLogical(oc_output_id_t id) const;
    bool getDigitalOutputPhysicalHigh(oc_output_id_t id) const;


private:
    static void managerTask(void* pvParameters);
    void processButtons(const ControllerState& cs);
    void adjustLedForBattery();
    void updateAuxOutput(oc_output_id_t id, uint8_t pin, PulseOutput& pulse, const ControllerState& cs, bool connected);
    void updateDigitalOutput(oc_output_id_t id, uint8_t pin, const ControllerState& cs, bool connected);
    void updatePulseOutput(oc_output_id_t id, PulseOutput& pulse, const ControllerState& cs, bool connected);
    bool evaluateDigitalOutput(const oc_output_cfg_t* cfg, const ControllerState& cs, bool previousState) const;
    bool weaponRoleArmed(const oc_output_cfg_t* cfg, const ControllerState& cs) const;
    uint16_t readConfigSourceMagnitude(oc_source_id_t src, const ControllerState& cs) const;
    int16_t readConfigSource(oc_source_id_t src, const ControllerState& cs) const;
    PulseProtocol protocolFromConfig(const oc_output_cfg_t* cfg) const;
    PulseEscSemantics escSemanticsFromConfig(const oc_output_cfg_t* cfg) const;
    bool updateEscArming(oc_output_id_t id, PulseOutput& pulse, const oc_output_cfg_t* cfg, const ControllerState& cs, const PulseProtocol& protocol);

    struct EscArmState {
        bool armed = false;
        bool sequence_running = false;
        uint32_t sequence_started_ms = 0;
        uint32_t hold_started_ms = 0;
        uint32_t signature = 0;
    };

    Drive drive;
    PulseOutput _s1Pulse;
    PulseOutput _s2Pulse;
    PowerFunctions powerFunctions;
    Buttons buttons;
    LED led;
    rgbLED ledStrip;

    // controller state (written by update(), read by managerTask)
    volatile bool    _isConnected;
    volatile int16_t _leftDriveInput;
    volatile int16_t _rightDriveInput;
    volatile int16_t _leftTurnInput;
    volatile int16_t _rightTurnInput;
    volatile int16_t _forwardEscInput;
    volatile int16_t _reverseEscInput;
    volatile uint16_t _buttonsInput;
    volatile uint16_t _dpadInput;
    volatile bool pendingUpdate;
    volatile uint32_t lastUpdateTime;

    uint32_t _controllerTimeout;
    volatile bool     motorsStopped = true;
    volatile int8_t   batteryState = -1;

    volatile uint8_t  currentOrientation = RIGHTSIDE_UP;

    volatile bool _s1DigitalLogical = false;
    volatile bool _s1DigitalPhysicalHigh = false;
    volatile bool _s2DigitalLogical = false;
    volatile bool _s2DigitalPhysicalHigh = false;

    EscArmState _s1EscArm;
    EscArmState _s2EscArm;

    TaskHandle_t taskHandle;
};

#endif
