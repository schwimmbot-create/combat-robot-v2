from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "components/myrobot/src/TaskManager.cpp").read_text()


def arcade_turn_priority(throttle: int, steering: int) -> tuple[int, int]:
    drive = (throttle * (512 - abs(steering))) // 512
    return max(-512, min(511, drive + steering)), max(-512, min(511, drive - steering))


def test_hard_turn_preserves_full_differential_with_trigger_throttle():
    # At full steering, forward trigger must not reduce yaw authority.
    assert arcade_turn_priority(0, 511) == (511, -511)
    assert arcade_turn_priority(511, 511) == (511, -511)


def test_arcade_mixing_suppresses_throttle_proportionally_as_turn_increases():
    straight = arcade_turn_priority(511, 0)
    medium = arcade_turn_priority(511, 256)
    assert straight == (511, 511)
    assert medium == (511, -1)  # integer quantization around neutral


def test_firmware_uses_turn_priority_mixer():
    assert "throttle * (512 - abs(steering))" in SOURCE
    assert "Preserve full yaw authority" in SOURCE
