#include <Arduino.h>
#include "Constants.h"
#include "Drive.h"
#include "DriveMotor.h"
#include "esp_log.h"

static const char* TAG = "Drive";

static inline int16_t zero_small_drive_command(int16_t value) {
    return abs(value) <= 1 ? 0 : value;
}


Drive::Drive(): leftMotor(DRIVE_MOTOR1_1_PIN, DRIVE_MOTOR1_2_PIN,
                          DRIVE_MOTOR1_FWD_PWM_CHANNEL,
                          DRIVE_MOTOR1_REV_PWM_CHANNEL,
                          false),
rightMotor(DRIVE_MOTOR2_1_PIN, DRIVE_MOTOR2_2_PIN,
           DRIVE_MOTOR2_FWD_PWM_CHANNEL,
           DRIVE_MOTOR2_REV_PWM_CHANNEL,
           false){
    setForwardInputLimits();
    setLateralInputLimits();
    //setPwmResolution();
}
//Programming note:  called a member initialization list, and it is used in the constructor 
//of a class to initialize the member variables before the body of the constructor is executed.

void Drive::begin(){
    leftMotor.begin();
    rightMotor.begin();
    maxPwmVal = (1 << DRIVE_MOTOR_PWM_RESOLUTION) - 1;
    ESP_LOGD(TAG, "Max PWM: %d", maxPwmVal);
}

void Drive::setMotorPwmFrequency(bool left_motor, uint16_t frequency_hz){
    if (left_motor) leftMotor.setPwmFrequency(frequency_hz);
    else rightMotor.setPwmFrequency(frequency_hz);
}

DriveMotorIntent Drive::getMotorIntent(bool left_motor) const {
    return left_motor ? leftMotor.getIntent() : rightMotor.getIntent();
}

/**
 * Sets the minimum and maximum expected input values to set the speed to.
 * Default: -512 to 511
 * @param minInput      Minimum input value from the controller
 * @param maxInput      Maximum input value from the controller
 */
void Drive::setForwardInputLimits(int minInput, int maxInput){
    _minForwardInput = minInput;
    _maxForwardInput = maxInput;
}

/**
 * Sets the minimum and maximum expected input values to set the speed to.
 * Default: -512 to 511
 * @param minInput      Minimum input value from the controller
 * @param maxInput      Maximum input value from the controller
 */
void Drive::setLateralInputLimits(int minInput, int maxInput){
    _minLateralInput = minInput;
    _maxLateralInput = maxInput;
}


/**
 * Sets the number of bits the the PWM resolution will consist of
 * Default: 8 
 * @param resolution        Number of bits in the PWM resolution
 */
/*
void Drive::setPwmResolution(int resolution){
    _resolution = resolution;
    _resolution = constrain(_resolution, 8, 12);
    maxPwmVal = (2^_resolution)-1;
}
*/

/**
 * Sets the speed of both drive motors to provide direction.
 * Call setInputLimits() to define the X and Y input range 
 * 
 * @param joystick_x             Joystick X Input 
 * @param joystick_y             Joystick Y Input 
 * @param orientation   Declare whether the robot is rightside up or upside down
 */
void Drive::combined_direction(int joystick_x, int joystick_y, byte orientation){
    combined_direction(joystick_x, joystick_y, orientation, true, true);
}

void Drive::combined_direction(int joystick_x, int joystick_y, byte orientation, bool left_enabled, bool right_enabled){
    int16_t x_input = joystick_x;
    int16_t y_input = joystick_y;

    int16_t x_input_mapped = map(x_input, _minLateralInput, _maxLateralInput, -maxPwmVal, maxPwmVal);
    int16_t y_input_mapped = map(y_input, _minForwardInput, _maxForwardInput, -maxPwmVal, maxPwmVal);

    int16_t leftMotorSpeed;
    int16_t rightMotorSpeed;

    //If bot is flipped, motors must rotate the opposite direction 
    //to go forward and Right<->Left are swapped now
    if(orientation == RIGHTSIDE_UP){
        leftMotorSpeed = y_input_mapped + x_input_mapped;
        rightMotorSpeed = y_input_mapped - x_input_mapped;
    }
    else if(orientation == UPSIDE_DOWN){
        leftMotorSpeed = y_input_mapped - x_input_mapped;
        rightMotorSpeed = y_input_mapped + x_input_mapped;
    }
    leftMotorSpeed = zero_small_drive_command(leftMotorSpeed);
    rightMotorSpeed = zero_small_drive_command(rightMotorSpeed);

    //Convert back to 0 to Max PWM Value range for out drive motor input
    //Set direction based on positive or negative
    int left_speed = constrain(abs(leftMotorSpeed), 0, maxPwmVal);
    int right_speed = constrain(abs(rightMotorSpeed), 0, maxPwmVal);

    if (left_enabled) {
        if(left_speed == 0){leftMotor.setSpeed(0, STOP, RIGHTSIDE_UP);}
        else if(leftMotorSpeed < 0){leftMotor.setSpeed(left_speed, REVERSE, orientation);}
        else{leftMotor.setSpeed(left_speed, FORWARD, orientation);}
    } else {
        leftMotor.setSpeed(0, STOP, RIGHTSIDE_UP);
    }

    if (right_enabled) {
        if(right_speed == 0){rightMotor.setSpeed(0, STOP, RIGHTSIDE_UP);}
        else if(rightMotorSpeed < 0){rightMotor.setSpeed(right_speed, REVERSE, orientation);}
        else{rightMotor.setSpeed(right_speed, FORWARD, orientation);}
    } else {
        rightMotor.setSpeed(0, STOP, RIGHTSIDE_UP);
    }
}


/**
 * Sets the speed of the motors indiviually using two joysticks, one dedicated for each motor
 * 
 * @param left_input             Input to Control Left Motor
 * @param right_input            Input to Control the Right Motor 
 * @param orientation            Declare whether the robot is rightside up or upside down
 */
void Drive::two_stick_drive(int left_input, int right_input, byte orientation){
    two_stick_drive(left_input, right_input, orientation, true, true);
}

void Drive::two_stick_drive(int left_input, int right_input, byte orientation, bool left_enabled, bool right_enabled){

    int leftMotorSpeed = map(left_input, _minForwardInput, _maxForwardInput, -maxPwmVal, maxPwmVal);
    int rightMotorSpeed = map(right_input, _minForwardInput, _maxForwardInput, -maxPwmVal, maxPwmVal);


    //If bot is flipped, Left is now right, right is left
    if(orientation == UPSIDE_DOWN){
        int16_t temp = leftMotorSpeed;
        leftMotorSpeed = rightMotorSpeed;
        rightMotorSpeed = temp;
    }
    leftMotorSpeed = zero_small_drive_command(leftMotorSpeed);
    rightMotorSpeed = zero_small_drive_command(rightMotorSpeed);

    //Convert back to 0 to Max PWM Value range for out drive motor input
    //Set direction based on positive or negative
    int left_speed = constrain(abs(leftMotorSpeed), 0, maxPwmVal);
    int right_speed = constrain(abs(rightMotorSpeed), 0, maxPwmVal);

    if (left_enabled) {
        if(left_speed == 0){leftMotor.setSpeed(0, STOP, RIGHTSIDE_UP);}
        else if(leftMotorSpeed < 0){leftMotor.setSpeed(left_speed, REVERSE, orientation);}
        else{leftMotor.setSpeed(left_speed, FORWARD, orientation);}
    } else {
        leftMotor.setSpeed(0, STOP, RIGHTSIDE_UP);
    }

    if (right_enabled) {
        if(right_speed == 0){rightMotor.setSpeed(0, STOP, RIGHTSIDE_UP);}
        else if(rightMotorSpeed < 0){rightMotor.setSpeed(right_speed, REVERSE, orientation);}
        else{rightMotor.setSpeed(right_speed, FORWARD, orientation);}
    } else {
        rightMotor.setSpeed(0, STOP, RIGHTSIDE_UP);
    }

}


void Drive::single_motor_drive(bool left_motor, int input, byte orientation, bool enabled){
    int motorSpeed = map(input, _minForwardInput, _maxForwardInput, -maxPwmVal, maxPwmVal);
    motorSpeed = zero_small_drive_command(motorSpeed);
    int speed = constrain(abs(motorSpeed), 0, maxPwmVal);
    if (!enabled || speed == 0) {
        if (left_motor) leftMotor.setSpeed(0, STOP, RIGHTSIDE_UP);
        else rightMotor.setSpeed(0, STOP, RIGHTSIDE_UP);
        return;
    }
    if (motorSpeed < 0) {
        if (left_motor) leftMotor.setSpeed(speed, REVERSE, orientation);
        else rightMotor.setSpeed(speed, REVERSE, orientation);
    } else {
        if (left_motor) leftMotor.setSpeed(speed, FORWARD, orientation);
        else rightMotor.setSpeed(speed, FORWARD, orientation);
    }
}

//Stop both drive motors
void Drive::stop(){
    stopLeft();
    stopRight();
}

void Drive::stopLeft(){
    leftMotor.setSpeed(0, STOP, RIGHTSIDE_UP);
}

void Drive::stopRight(){
    rightMotor.setSpeed(0, STOP, RIGHTSIDE_UP);
}

/*ChatgGPT suggested drive style

// Helpers
static inline float clampf(float v, float lo, float hi){ return v < lo ? lo : (v > hi ? hi : v); }

static inline float applyDeadband(float x, float db){
    if (fabsf(x) <= db) return 0.0f;
    // re-scale so remaining range maps back to [-1,1]
    return (x > 0.0f) ? (x - db) / (1.0f - db) : (x + db) / (1.0f - db);
}

// Expo curve: out = (1 - expo)*x + expo*(x^3). expo in [0..1]
static inline float expoCurve(float x, float expo){
    return (1.0f - expo)*x + expo*(x*x*x);
}

// Simple per-side slew limiter (units: fraction of full-scale per call)
struct SlewLimiter {
    float prev = 0.0f;
    float rise = 0.12f;  // max step up per tick (0..1)
    float fall = 0.20f;  // max step down per tick (0..1) - let braking be sharper
    float apply(float target){
        float delta = target - prev;
        float lim = (delta >= 0.0f) ? rise : -fall;
        if (fabsf(delta) > fabsf(lim)) prev += lim;
        else prev = target;
        return prev;
    }
};

void Drive::two_stick_drive(int left_input, int right_input, byte orientation){

    // ---- TUNABLES ----
    const float deadband    = 0.06f;  // ignore tiny stick noise
    const float expo        = 0.6f;   // 0 = linear, 1 = very gentle center / aggressive ends
    const float precisionScale = 1.0f; // e.g., set to 0.5f when a "precision mode" button is held
    const float turnDamp    = 0.10f;  // reduce output during counter-rotation (0..0.3 is typical)

    static SlewLimiter slewL, slewR;  // persists across calls

    // 1) Normalize inputs to [-1, 1] as floats (use your calibrated min/max)
    float l = (float)(left_input  - _minForwardInput)  / (float)(_maxForwardInput - _minForwardInput) * 2.0f - 1.0f;
    float r = (float)(right_input - _minForwardInput)  / (float)(_maxForwardInput - _minForwardInput) * 2.0f - 1.0f;
    l = clampf(l, -1.0f, 1.0f);
    r = clampf(r, -1.0f, 1.0f);

    // 2) Deadband
    l = applyDeadband(l, deadband);
    r = applyDeadband(r, deadband);

    // 3) Expo shaping (gentle around center but preserves full-scale at ends)
    l = expoCurve(l, expo);
    r = expoCurve(r, expo);

    // 4) Optional precision scale (wire to a button if you want)
    l *= precisionScale;
    r *= precisionScale;

    // 5) Turn damping: when sticks are opposite signs (in-place spin), trim a bit
    if ((l > 0 && r < 0) || (l < 0 && r > 0)) {
        l *= (1.0f - turnDamp);
        r *= (1.0f - turnDamp);
    }

    // 6) Orientation swap if flipped
    if (orientation == UPSIDE_DOWN){
        float tmp = l; l = r; r = tmp;
    }

    // 7) Slew rate limit (keeps it responsive but prevents sudden jumps)
    l = slewL.apply(clampf(l, -1.0f, 1.0f));
    r = slewR.apply(clampf(r, -1.0f, 1.0f));

    // 8) Scale to PWM range and command motors
    int leftMotorSpeed  = (int)roundf(l * (float)maxPwmVal);
    int rightMotorSpeed = (int)roundf(r * (float)maxPwmVal);

    int left_speed  = constrain(abs(leftMotorSpeed),  0, maxPwmVal);
    int right_speed = constrain(abs(rightMotorSpeed), 0, maxPwmVal);

    if (leftMotorSpeed < 0)  { leftMotor.setSpeed(left_speed,  REVERSE, orientation); }
    else                     { leftMotor.setSpeed(left_speed,  FORWARD, orientation); }

    if (rightMotorSpeed < 0) { rightMotor.setSpeed(right_speed, REVERSE, orientation); }
    else                     { rightMotor.setSpeed(right_speed, FORWARD, orientation); }
}

*/


