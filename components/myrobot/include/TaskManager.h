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
    uint16_t getAuxPulseUs(oc_output_id_t id) const;
    uint16_t getAuxDuty(oc_output_id_t id) const;
    const char* getEscArmPhaseName(oc_output_id_t id) const;
    int16_t getDriveThrottle() const;
    int16_t getDriveSteering() const;
    int16_t getDriveLeftCommand() const;
    int16_t getDriveRightCommand() const;


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
    int16_t readDriveAxis(oc_drive_axis_t axis, const ControllerState& cs) const;
    bool driveModifierActive(oc_source_id_t src, const ControllerState& cs) const;
    bool manualMotorSourceActive(const oc_output_cfg_t* cfg, const ControllerState& cs) const;
    int16_t manualMotorCommand(oc_output_id_t id, const oc_output_cfg_t* cfg, const ControllerState& cs, bool connected, bool allowed);
    int16_t applyDriveModifiersToThrottle(int16_t throttle, const oc_drive_setup_t* setup, const ControllerState& cs) const;
    int16_t applyDriveModifiersToSteering(int16_t steering, const oc_drive_setup_t* setup, const ControllerState& cs) const;
    void updateSteeringServo(oc_output_id_t id, int16_t steering, const ControllerState& cs, bool connected);
    bool outputReservedForDriveSteering(oc_output_id_t id) const;
    bool updateEscArming(oc_output_id_t id, PulseOutput& pulse, const oc_output_cfg_t* cfg, const ControllerState& cs, const PulseProtocol& protocol);

    enum EscArmPhase : uint8_t {
        ESC_ARM_PHASE_INACTIVE = 0,
        ESC_ARM_PHASE_MANUAL,
        ESC_ARM_PHASE_WAITING,
        ESC_ARM_PHASE_HOLDING,
        ESC_ARM_PHASE_LOW1,
        ESC_ARM_PHASE_HIGH,
        ESC_ARM_PHASE_LOW2,
        ESC_ARM_PHASE_ARMED,
    };

    struct EscArmState {
        bool armed = false;
        bool sequence_running = false;
        uint32_t sequence_started_ms = 0;
        uint32_t hold_started_ms = 0;
        uint32_t signature = 0;
        EscArmPhase phase = ESC_ARM_PHASE_INACTIVE;
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
    volatile int16_t _driveThrottle = 0;
    volatile int16_t _driveSteering = 0;
    volatile int16_t _driveLeftCommand = 0;
    volatile int16_t _driveRightCommand = 0;
    bool _m1Latched = false;
    bool _m2Latched = false;
    bool _m1PrevManualActive = false;
    bool _m2PrevManualActive = false;

    EscArmState _s1EscArm;
    EscArmState _s2EscArm;

    TaskHandle_t taskHandle;
};

#endif
