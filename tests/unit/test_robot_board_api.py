from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HEADER=ROOT/'components/robot_board/include/SchwimmRobotBoard.h'
SOURCE=ROOT/'components/robot_board/src/SchwimmRobotBoard.cpp'
DOC=ROOT/'docs/arduino-api/README.md'
SMOKE=ROOT/'main/robot_board_api_compile_smoke.cpp'


def test_public_api_surface_and_units_are_documented():
    h=HEADER.read_text(); doc=DOC.read_text()
    for name in ('SchwimmRobotBoard','RobotDrive','MotorChannel','ServoChannel','EscChannel','ControllerInput','PowerMonitor','ConfigStore'):
        assert f'class {name}' in h
        assert name in h+doc
    for unit in ('-512..511','0..180 degrees','microseconds','-100..100%'):
        assert unit in doc


def test_safety_contract_is_enforced_in_source():
    s=SOURCE.read_text(); h=HEADER.read_text()
    assert 'if(!_armed){safe();return;}' in s
    assert 'if(!_controller.connected())stopAll();' in s
    assert 'void SchwimmRobotBoard::stopAll()' in s
    assert "OneShot42" in h and "MultiShot" in h
    assert "Experimental" not in h
    assert "disconnect_failsafe" not in h  # no public bypass knob


def test_examples_compile_smoke_exercises_every_wrapper():
    smoke=SMOKE.read_text()
    for token in ('robot.drive()','robot.motor(','robot.servo(','robot.esc(','robot.controller()','robot.power()','robot.config()','robot.stopAll()'):
        assert token in smoke
    assert '-I components/robot_board/include' in (ROOT/'platformio.ini').read_text()


def test_shared_aux_pulse_ownership_prevents_duplicate_hardware_instances():
    h=HEADER.read_text()
    assert 'PulseOutput _pulse1,_pulse2' in h
    assert 'ServoChannel _servo1,_servo2' in h
    assert 'EscChannel _esc1,_esc2' in h
