#pragma once

#include <Arduino.h>
#include "Drive.h"
#include "PulseOutput.h"
#include "PowerFunctions.h"
#include "ble_gamepad.h"
#include "output_config.h"
#include "battery_config.h"

enum class DriveStyle : uint8_t { Tank, Arcade, ServoSteering };
enum class EscProtocol : uint8_t { RcPwm, OneShot, OneShot125, OneShot42, MultiShot };
enum class BatteryLevel : uint8_t { Good, Warning, Low };

enum RobotButton : uint16_t {
  ROBOT_BTN_A=0x0001, ROBOT_BTN_B=0x0002, ROBOT_BTN_X=0x0004, ROBOT_BTN_Y=0x0008,
  ROBOT_BTN_L1=0x0010, ROBOT_BTN_R1=0x0020, ROBOT_BTN_L2=0x0040, ROBOT_BTN_R2=0x0080,
  ROBOT_BTN_SELECT=0x0100, ROBOT_BTN_START=0x0200, ROBOT_BTN_L3=0x0400,
  ROBOT_BTN_R3=0x0800, ROBOT_BTN_HOME=0x1000,
};

class ServoChannel;

class RobotDrive {
public:
  void begin();
  void setStyle(DriveStyle style) { _style=style; }
  DriveStyle style() const { return _style; }
  void tank(int left, int right);
  void arcade(int throttle, int steering);
  void servoSteer(int throttle, int steering);
  void bindSteeringServo(ServoChannel& servo) { _steeringServo=&servo; }
  void stop();
  DriveMotorIntent motorIntent(uint8_t id) const;
  Drive& raw() { return _drive; }
private:
  Drive _drive;
  DriveStyle _style=DriveStyle::Tank;
  ServoChannel* _steeringServo=nullptr;
};

class MotorChannel {
public:
  MotorChannel(RobotDrive& drive, uint8_t id):_drive(drive),_id(id){}
  void setPercent(float percent);
  void stop();
  void setFrequencyHz(uint16_t hz);
  DriveMotorIntent intent() const { return _drive.motorIntent(_id); }
private:
  RobotDrive& _drive; uint8_t _id;
};

class ServoChannel {
public:
  ServoChannel(PulseOutput& pulse, oc_output_id_t id):_pulse(pulse),_id(id){}
  void begin();
  void setRange(uint16_t minUs, uint16_t centerUs, uint16_t maxUs);
  void writeDegrees(float degrees);
  void writeMicroseconds(uint16_t us);
  void center();
  uint16_t lastPulseUs() const { return _pulse.lastPulseUs(); }
private:
  PulseOutput& _pulse; oc_output_id_t _id; uint16_t _min=1000,_center=1500,_max=2000;
};

class EscChannel {
public:
  EscChannel(PulseOutput& pulse, oc_output_id_t id):_pulse(pulse),_id(id){}
  void begin(EscProtocol protocol=EscProtocol::RcPwm, bool bidirectional=false);
  bool arm();
  void update();
  bool isArmed() const { return _armed; }
  const char* armPhaseName() const;
  void setPercent(float percent);
  void setForwardPercent(float percent);
  void safe();
  uint16_t lastPulseUs() const { return _pulse.lastPulseUs(); }
private:
  enum class Phase:uint8_t { Safe, Low, High, FinalLow, Armed };
  PulseOutput& _pulse; oc_output_id_t _id; PulseProtocol _protocol=PULSE_PROTOCOL_RC_ESC_PWM;
  PulseEscSemantics _semantics=PULSE_ESC_FORWARD_ONLY; Phase _phase=Phase::Safe; uint32_t _phaseAt=0; bool _armed=false;
};

class ControllerInput {
public:
  void begin();
  void update();
  bool connected() const { return _connected; }
  int leftX() const { return axis(_state.leftStickX); } int leftY() const { return axis(_state.leftStickY); }
  int rightX() const { return axis(_state.rightStickX); } int rightY() const { return axis(_state.rightStickY); }
  int leftTrigger() const { return _state.leftTrigger; } int rightTrigger() const { return _state.rightTrigger; }
  bool button(uint16_t mask) const { return (_state.buttons&mask)!=0; }
  bool pressed(uint16_t mask) const { return (_state.buttons&mask)!=0 && (_previous.buttons&mask)==0; }
  bool released(uint16_t mask) const { return (_state.buttons&mask)==0 && (_previous.buttons&mask)!=0; }
  bool dpadUp() const; bool dpadDown() const; bool dpadLeft() const; bool dpadRight() const;
  void setDeadzone(uint16_t value) { _deadzone=value>511?511:value; }
  const ControllerState& state() const { return _state; }
private:
  int axis(int value) const { return abs(value)<_deadzone?0:value; }
  ControllerState _state{},_previous{}; bool _connected=false; uint16_t _deadzone=30;
};

class PowerMonitor {
public:
  void begin();
  uint16_t millivolts() const { return PowerFunctions::getLastBatteryMillivolts(); }
  uint16_t cellMillivolts() const;
  uint8_t percent() const { return PowerFunctions::getLastBatteryPercent(); }
  uint8_t cellCount() const { return battery_config_get_cell_count(); }
  BatteryLevel level() const;
  bool isGood() const { return level()==BatteryLevel::Good; } bool isWarning() const { return level()==BatteryLevel::Warning; } bool isLow() const { return level()==BatteryLevel::Low; }
private: PowerFunctions _power;
};

class ConfigStore {
public:
  bool begin(); bool save(); bool reset();
  bool motorReversed(uint8_t id) const;
  bool setMotorReversed(uint8_t id,bool reversed);
  DriveStyle driveStyle() const; bool setDriveStyle(DriveStyle style);
};

class SchwimmRobotBoard {
public:
  SchwimmRobotBoard();
  bool begin(); void update(); void stopAll();
  RobotDrive& drive(){return _drive;} MotorChannel& motor(uint8_t id){return id?_m2:_m1;}
  ServoChannel& servo(uint8_t id){return id?_servo2:_servo1;} EscChannel& esc(uint8_t id){return id?_esc2:_esc1;}
  ControllerInput& controller(){return _controller;} PowerMonitor& power(){return _power;} ConfigStore& config(){return _config;}
private:
  RobotDrive _drive; MotorChannel _m1,_m2; PulseOutput _pulse1,_pulse2;
  ServoChannel _servo1,_servo2; EscChannel _esc1,_esc2; ControllerInput _controller; PowerMonitor _power; ConfigStore _config;
};
