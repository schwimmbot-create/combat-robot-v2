from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BOARD_CONFIG = PROJECT_ROOT / "components" / "board_config" / "include" / "board_config.h"


@dataclass(frozen=True)
class BoardData:
    rev: int
    name: str
    revision: str
    num_drive_motors: int
    has_spare_header: bool
    pin_motor1_in1: int
    pin_motor1_in2: int
    pin_motor2_in1: int
    pin_motor2_in2: int
    pin_servo1: int
    pin_servo2: int
    wheel_base_m: float
    track_width_m: float
    max_speed_mps: float
    servo_wheel_base_m: float
    max_steering_angle_deg: float

    @property
    def chassis_kind(self) -> str:
        return "four_wheel_skid" if self.num_drive_motors >= 4 else "differential"

    @property
    def summary(self) -> str:
        return f"BOARD_REV={self.rev} {self.name} ({self.revision}), {self.num_drive_motors} drive motors"


def _board_block(text: str, rev: int) -> str:
    if rev == 2:
        pattern = r"#if BOARD_REV == 2(?P<body>[\s\S]*?)#elif BOARD_REV == 3"
    elif rev == 3:
        pattern = r"#elif BOARD_REV == 3(?P<body>[\s\S]*?)#else"
    else:
        raise ValueError(f"unsupported BOARD_REV {rev}; expected 2 or 3")
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f"BOARD_REV {rev} block not found in {BOARD_CONFIG}")
    return match.group("body")


def _define_str(block: str, name: str) -> str:
    match = re.search(rf"#define\s+{re.escape(name)}\s+\"([^\"]+)\"", block)
    if not match:
        raise ValueError(f"{name} string define not found")
    return match.group(1)


def _define_int(block: str, name: str, aliases: dict[str, int] | None = None) -> int:
    aliases = aliases or {}
    match = re.search(rf"#define\s+{re.escape(name)}\s+([^\s/]+)", block)
    if not match:
        raise ValueError(f"{name} int define not found")
    token = match.group(1)
    if token in aliases:
        return aliases[token]
    try:
        return int(token, 0)
    except ValueError as exc:
        raise ValueError(f"{name} value {token!r} is not an int or known alias") from exc


def load_board_data(rev: int = 2, path: str | Path = BOARD_CONFIG) -> BoardData:
    text = Path(path).read_text(encoding="utf-8")
    block = _board_block(text, rev)
    aliases = {
        "PIN_MOTOR1_IN1": _define_int(block, "PIN_MOTOR1_IN1"),
        "PIN_MOTOR1_IN2": _define_int(block, "PIN_MOTOR1_IN2"),
        "PIN_MOTOR2_IN1": _define_int(block, "PIN_MOTOR2_IN1"),
        "PIN_MOTOR2_IN2": _define_int(block, "PIN_MOTOR2_IN2"),
    }
    num_drive_motors = _define_int(block, "NUM_DRIVE_MOTORS")
    # Board data currently has electronics topology, not physical chassis dimensions.
    # Use conservative defaults derived by board capability; robot-specific values can
    # be layered later without changing the board parser.
    if num_drive_motors >= 4:
        wheel_base_m = 0.22
        track_width_m = 0.20
        max_speed_mps = 1.0
    else:
        wheel_base_m = 0.18
        track_width_m = 0.18
        max_speed_mps = 1.0
    return BoardData(
        rev=rev,
        name=_define_str(block, "BOARD_NAME"),
        revision=_define_str(block, "BOARD_REVISION_STRING"),
        num_drive_motors=num_drive_motors,
        has_spare_header=bool(_define_int(block, "HAS_SPARE_HEADER")),
        pin_motor1_in1=_define_int(block, "PIN_MOTOR1_IN1"),
        pin_motor1_in2=_define_int(block, "PIN_MOTOR1_IN2"),
        pin_motor2_in1=_define_int(block, "PIN_MOTOR2_IN1"),
        pin_motor2_in2=_define_int(block, "PIN_MOTOR2_IN2"),
        pin_servo1=_define_int(block, "PIN_SERVO1", aliases),
        pin_servo2=_define_int(block, "PIN_SERVO2", aliases),
        wheel_base_m=wheel_base_m,
        track_width_m=track_width_m,
        max_speed_mps=max_speed_mps,
        servo_wheel_base_m=0.22,
        max_steering_angle_deg=35.0,
    )


def supported_board_revs(path: str | Path = BOARD_CONFIG) -> list[int]:
    text = Path(path).read_text(encoding="utf-8")
    revs = [int(m.group(1)) for m in re.finditer(r"BOARD_REV == (\d+)", text)]
    return sorted(set(revs))
