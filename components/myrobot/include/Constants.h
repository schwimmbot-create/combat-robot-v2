#ifndef CONSTANTS_H
#define CONSTANTS_H

#include <Arduino.h>

const char VERSION[] = "Version 1.3";

//Modifiable Values
//#undef LOG_LOCAL_LEVEL
//#define LOG_LOCAL_LEVEL ESP_LOG_VERBOSE

#define TASK_MANAGER_READ_FREQ 50

#define ENABLE_LOW_BATTERY_SHUTDOWN true

#define DRIVE_MOTOR_PWM_FREQ 20000
#define DRIVE_MOTOR_PWM_RESOLUTION 8
// LEDC channels for the v2.0.14 Arduino-ESP32 framework. The v1.3
// framework didn't expose channels (it hid them behind ledcAttach).
// Each physical PWM output needs its own LEDC channel. Sharing a channel
// between M1 and M2 makes the second setSpeed() write drive both motors.
#define DRIVE_MOTOR1_FWD_PWM_CHANNEL 0
#define DRIVE_MOTOR1_REV_PWM_CHANNEL 1
#define DRIVE_MOTOR2_FWD_PWM_CHANNEL 2
#define DRIVE_MOTOR2_REV_PWM_CHANNEL 3

//Settings for DShot125 Signal
#define ESC_PWM_FREQ 2000
#define ESC_PWM_RESOLUTION 8
#define AUX_PWM_RESOLUTION 14

// ESP32-C3 Arduino exposes LEDC channels 0..5. Drive motors consume 0..3;
// S1/S2 pulse roles consume the remaining two channels.
#define LED_PWM_CHANNEL 5
#define SERVO1_PWM_CHANNEL 4
#define SERVO2_PWM_CHANNEL 5

#define CONTROLLER_TIMEOUT 1000 //How many milliseconds before shutting off motors without a signal from BLE Controller

//Push Button Settings
enum ButtonPress {
    BUTTON_NONE = 0,
    BUTTON_SHORT,
    BUTTON_DOUBLE,
    BUTTON_LONG,
    // Hold SW1 for the configured hold duration. Default is 5 seconds.
    // Used to clear the controller whitelist and enter pairing mode from the physical button.
    BUTTON_HOLD_5S
};
#define BUTTON_LOGIC_LEVEL LOW //Logic Level when button is pressed
#define DEBOUNCE_TIME 10 //milliseconds
#define LONG_PRESS_TIME 1000 //milliseconds
#define HOLD_5S_TIME 5000 //milliseconds
#define DOUBLE_PRESS_TIME 350 //milliseconds
#define BUTTON_READ_WAIT 50 //read every ___ milliseconds

//Battery Settings
const uint16_t MIN_MVOLT_PER_CELL = 3600; //millivolts
const uint16_t WARN_MVOLT_PER_CELL = 3750; //millivolts
const uint16_t NUM_OF_CELLS = 3; 

const uint16_t BATT_READ_FREQ = 100; //Frequency to measure batttery voltage for safety shutdown
const uint8_t BATT_SAMPLE_COUNT = 5; //How many Sample to average of a battery measurement
const uint16_t SAMPLE_PERIOD = 10; //Time between multiple battery voltage samples
const uint16_t BATTERY_DEBOUNCE_TIME = 3000; //Time in milliseconds that the battery voltage must be below threshold to be considered low voltage. Helps ignore voltage sag
const float BATTERY_MULTIPLIER = 8.95; //Voltage divider: (27k + 10k)/3k
const float EMA_ALPHA = 0.1f;  //Battery voltage measurement EMA filter value 
const float BATT_HYSTERESIS = 100.0f; //millivolt that voltage must go above to be considered above low voltage again

//Controller Inputs
// NOTE: This struct is included from BOTH C and C++ files. Do NOT use
// C++-only features (default member initializers, namespaces, etc.) here.
struct ControllerState {
    int  leftStickX;
    int  leftStickY;
    int  rightStickX;
    int  rightStickY;
    int  rightTrigger;
    int  leftTrigger;
    uint16_t  buttons;
    uint16_t  dpad;
};

//Board Specific Settings
#define ESC_1_PIN 4
#define ESC_2_PIN 8

// Legacy myrobot pin aliases. Keep these aligned with the live v2 board.
// Kevin verified v2 LED1 is IO10 and SW1 / ModeButton is IO5.
#define DRIVE_MOTOR1_1_PIN 1
#define DRIVE_MOTOR1_2_PIN 3
#define DRIVE_MOTOR2_1_PIN 6
#define DRIVE_MOTOR2_2_PIN 7

#define MODE_BUTTON_PIN 5
#define DEBUG_LED_PIN 10
#define BATT_MEAS_PIN 0

//Naming
#define LEFT 1
#define CENTER 2
#define RIGHT 3

#define FORWARD 1
#define REVERSE 2
#define STOP 3
#define RIGHTSIDE_UP 4
#define UPSIDE_DOWN 5

#define BATTERY_GOOD 1
#define BATTERY_WARN 2
#define BATTERY_LOW 3

#define APP_CPU_NUM 0

#endif