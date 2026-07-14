#include "SchwimmRobotBoard.h"
#include <math.h>

static int clampAxis(int v){ return constrain(v,-512,511); }
static float clampPct(float v){ return v<-100?-100:(v>100?100:v); }

void RobotDrive::begin(){ _drive.begin(); }
void RobotDrive::tank(int left,int right){ _style=DriveStyle::Tank; _drive.two_stick_drive(clampAxis(left),clampAxis(right),RIGHTSIDE_UP); }
void RobotDrive::arcade(int throttle,int steering){ _style=DriveStyle::Arcade; _drive.combined_direction(clampAxis(steering),clampAxis(throttle),RIGHTSIDE_UP); }
void RobotDrive::servoSteer(int throttle,int steering){ _style=DriveStyle::ServoSteering; _drive.single_motor_drive(true,clampAxis(throttle),RIGHTSIDE_UP); if(_steeringServo)_steeringServo->writeDegrees((clampAxis(steering)+512)*180.0f/1023.0f); }
void RobotDrive::stop(){ _drive.stop(); }
DriveMotorIntent RobotDrive::motorIntent(uint8_t id) const { return _drive.getMotorIntent(id==0); }
void MotorChannel::setPercent(float pct){ int v=(int)lroundf(clampPct(pct)*511.0f/100.0f); _drive.raw().single_motor_drive(_id==0,v,RIGHTSIDE_UP); }
void MotorChannel::stop(){ if(_id==0)_drive.raw().stopLeft();else _drive.raw().stopRight(); }
void MotorChannel::setFrequencyHz(uint16_t hz){ _drive.raw().setMotorPwmFrequency(_id==0,constrain(hz,1000,40000)); }

void ServoChannel::begin(){ const oc_output_cfg_t* c=output_config_get(_id); if(c){setRange(c->min_pulse_us,c->center_pulse_us,c->max_pulse_us);} _pulse.begin(PULSE_PROTOCOL_RC_SERVO_PWM); center(); }
void ServoChannel::setRange(uint16_t a,uint16_t c,uint16_t b){ if(a<c&&c<b){_min=a;_center=c;_max=b;} }
void ServoChannel::writeDegrees(float d){ d=constrain(d,0.0f,180.0f); uint16_t us=d<=90?_min+(uint16_t)((_center-_min)*d/90.0f):_center+(uint16_t)((_max-_center)*(d-90.0f)/90.0f); writeMicroseconds(us); }
void ServoChannel::writeMicroseconds(uint16_t us){ _pulse.writePulseUs(constrain(us,_min,_max)); }
void ServoChannel::center(){ _pulse.writePulseUs(_center); }

static PulseProtocol escProtocol(EscProtocol p){ switch(p){case EscProtocol::OneShot:return PULSE_PROTOCOL_ONESHOT;case EscProtocol::OneShot125:return PULSE_PROTOCOL_ONESHOT125;case EscProtocol::OneShot42:return PULSE_PROTOCOL_ONESHOT42;case EscProtocol::MultiShot:return PULSE_PROTOCOL_MULTISHOT;default:return PULSE_PROTOCOL_RC_ESC_PWM;} }
void EscChannel::begin(EscProtocol p,bool bi){_protocol=escProtocol(p);_semantics=bi?PULSE_ESC_BIDIRECTIONAL:PULSE_ESC_FORWARD_ONLY;_pulse.begin(_protocol);safe();}
bool EscChannel::arm(){ if(_armed)return true;_armed=false;_phase=Phase::Low;_phaseAt=millis();_pulse.writePulseUs(_protocol.min_us);return false; }
void EscChannel::update(){uint32_t now=millis();if(_phase==Phase::Low&&now-_phaseAt>=500){_pulse.writePulseUs(_protocol.max_us);_phase=Phase::High;_phaseAt=now;}else if(_phase==Phase::High&&now-_phaseAt>=500){_pulse.writePulseUs(_protocol.min_us);_phase=Phase::FinalLow;_phaseAt=now;}else if(_phase==Phase::FinalLow&&now-_phaseAt>=500){_armed=true;_phase=Phase::Armed;}}
const char* EscChannel::armPhaseName()const{switch(_phase){case Phase::Low:return"LOW";case Phase::High:return"HIGH";case Phase::FinalLow:return"FINAL_LOW";case Phase::Armed:return"ARMED";default:return"SAFE";}}
void EscChannel::setPercent(float pct){if(!_armed){safe();return;}pct=clampPct(pct);if(_semantics==PULSE_ESC_FORWARD_ONLY){setForwardPercent(pct<0?0:pct);return;}uint16_t us=pct>=0?_protocol.center_us+(uint16_t)((_protocol.max_us-_protocol.center_us)*pct/100.0f):_protocol.center_us-(uint16_t)((_protocol.center_us-_protocol.min_us)*(-pct)/100.0f);_pulse.writePulseUs(us);}
void EscChannel::setForwardPercent(float pct){if(!_armed){safe();return;}pct=constrain(pct,0.0f,100.0f);_pulse.writePulseUs(_protocol.min_us+(uint16_t)((_protocol.max_us-_protocol.min_us)*pct/100.0f));}
void EscChannel::safe(){_armed=false;_phase=Phase::Safe;_pulse.safeState(_semantics);}

void ControllerInput::begin(){ble_gamepad_init();ble_gamepad_start();}
void ControllerInput::update(){_previous=_state;ble_gamepad_poll();_state=ble_gamepad_get_state();_connected=ble_gamepad_is_connected();}
bool ControllerInput::dpadUp()const{return _state.dpad==0||_state.dpad==1||_state.dpad==7;} bool ControllerInput::dpadRight()const{return _state.dpad>=1&&_state.dpad<=3;} bool ControllerInput::dpadDown()const{return _state.dpad>=3&&_state.dpad<=5;} bool ControllerInput::dpadLeft()const{return _state.dpad>=5&&_state.dpad<=7;}
void PowerMonitor::begin(){battery_config_init();_power.begin();}
uint16_t PowerMonitor::cellMillivolts()const{uint8_t n=cellCount();return n?millivolts()/n:0;}
BatteryLevel PowerMonitor::level()const{uint8_t s=PowerFunctions::getLastBatteryState();return s==BATTERY_LOW?BatteryLevel::Low:(s==BATTERY_WARN?BatteryLevel::Warning:BatteryLevel::Good);}
bool ConfigStore::begin(){return output_config_init()==ESP_OK;}
bool ConfigStore::save(){return output_config_commit()==ESP_OK;}
bool ConfigStore::reset(){output_config_reset_defaults();return save();}
bool ConfigStore::motorReversed(uint8_t id)const{return output_config_get(id?OC_OUT_M2:OC_OUT_M1)->direction==OC_DIR_REVERSED;}
bool ConfigStore::setMotorReversed(uint8_t id,bool r){return output_config_set_direction(id?OC_OUT_M2:OC_OUT_M1,r?OC_DIR_REVERSED:OC_DIR_NORMAL)==ESP_OK;}
DriveStyle ConfigStore::driveStyle()const{const auto*s=output_config_get_drive_setup();return s->method==OC_DRIVE_METHOD_ARCADE?DriveStyle::Arcade:(s->method==OC_DRIVE_METHOD_SERVO_STEERING?DriveStyle::ServoSteering:DriveStyle::Tank);}
bool ConfigStore::setDriveStyle(DriveStyle style){oc_drive_setup_t s=*output_config_get_drive_setup();s.method=style==DriveStyle::Arcade?OC_DRIVE_METHOD_ARCADE:(style==DriveStyle::ServoSteering?OC_DRIVE_METHOD_SERVO_STEERING:OC_DRIVE_METHOD_TANK);s.layout=style==DriveStyle::ServoSteering?OC_DRIVE_LAYOUT_SERVO_STEERING:OC_DRIVE_LAYOUT_DIFFERENTIAL;return output_config_set_drive_setup(&s)==ESP_OK;}
SchwimmRobotBoard::SchwimmRobotBoard():_m1(_drive,0),_m2(_drive,1),_pulse1(ESC_1_PIN,SERVO1_PWM_CHANNEL,14),_pulse2(ESC_2_PIN,SERVO2_PWM_CHANNEL,14),_servo1(_pulse1,OC_OUT_S1),_servo2(_pulse2,OC_OUT_S2),_esc1(_pulse1,OC_OUT_S1),_esc2(_pulse2,OC_OUT_S2){}
bool SchwimmRobotBoard::begin(){if(!_config.begin())return false;_drive.begin();_drive.bindSteeringServo(_servo1);_servo1.begin();_controller.begin();_power.begin();return true;}
void SchwimmRobotBoard::update(){_controller.update();_esc1.update();_esc2.update();if(!_controller.connected())stopAll();}
void SchwimmRobotBoard::stopAll(){_drive.stop();_esc1.safe();_esc2.safe();}
