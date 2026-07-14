#include <SchwimmRobotBoard.h>

// Compiled with the normal firmware to keep the documented public API honest.
// This function is intentionally not called by the production sketch.
void robot_board_api_compile_smoke() {
  SchwimmRobotBoard robot;
  robot.begin();
  robot.drive().setStyle(DriveStyle::Arcade);
  robot.drive().arcade(robot.controller().leftY(), robot.controller().leftX());
  robot.motor(0).setPercent(25.0f);
  robot.motor(1).stop();
  robot.servo(0).begin();
  robot.servo(0).setRange(1000, 1500, 2000);
  robot.servo(0).writeDegrees(90);
  robot.esc(1).begin(EscProtocol::OneShot125, false);
  robot.esc(1).arm();
  robot.esc(1).setForwardPercent(20);
  if (robot.controller().pressed(ROBOT_BTN_A) || robot.power().isLow()) robot.stopAll();
  robot.config().setMotorReversed(0, false);
}
