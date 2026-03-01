import operator
from functools import reduce

MSG_LEN = 27
IDLE = bytes.fromhex("436d640001001200010404000a000000808080802020202000550f")
CMD_PREFIX = IDLE[:-11]
_CHECKSUM0_INIT = 0x55
_PAYLOAD_DATA_START = 16

# Network constants
DRONE_IP = "172.16.10.1"
DRONE_PORT = 5555
LOCAL_PORT = 6666

# Axis neutral positions
NEUTRAL = 0x80
TRIM_NEUTRAL = 0x20

# Special command byte values (payload byte 8)
SPECIAL_NONE = 0x00
SPECIAL_POWER_TOGGLE = 0x10
SPECIAL_LAND = 0x08
SPECIAL_CALIBRATE = 0x20

# Lift/auto-takeoff is encoded as trim_throttle=0x60, not via the special byte
LIFT_TRIM_THROTTLE = 0x60


def _c(cmd: str) -> bytes:
    data = bytes.fromhex(cmd)
    assert len(data) == MSG_LEN - len(CMD_PREFIX)
    return CMD_PREFIX + data


def checksum(msg: bytes) -> bytes:
    """Calculate dual-byte checksum for a 25-byte message (excluding checksum bytes).

    CHECKSUM0: XOR all 9 payload data bytes (msg[16:25]), then add 0x55.
    CHECKSUM1: Sum of all 25 bytes of msg (indices 0-24) plus CHECKSUM0, totaling 26 bytes.
    """
    payload_xor = reduce(operator.xor, msg[_PAYLOAD_DATA_START:], 0)
    b9 = (_CHECKSUM0_INIT + payload_xor) & 0xFF
    b10 = (sum(msg) + b9) & 0xFF
    return bytes((b9, b10))


def build_command(
    throttle: int = NEUTRAL,
    elevator: int = NEUTRAL,
    rudder: int = NEUTRAL,
    aileron: int = NEUTRAL,
    trim_elevator: int = TRIM_NEUTRAL,
    trim_rudder: int = TRIM_NEUTRAL,
    trim_aileron: int = TRIM_NEUTRAL,
    trim_throttle: int = TRIM_NEUTRAL,
    special: int = SPECIAL_NONE,
) -> bytes:
    """Build a 27-byte command packet from axis values, trims, and special command.

    Axes are 0x00-0xFF with 0x80 (NEUTRAL) as center.
    Trims are 0x00-0xFF with 0x20 (TRIM_NEUTRAL) as center.
    Special is one of the SPECIAL_* constants (0x00 for normal operation).
    """
    payload = bytes(
        (
            throttle,
            elevator,
            rudder,
            aileron,
            trim_elevator,
            trim_rudder,
            trim_aileron,
            trim_throttle,
            special,
        )
    )
    msg = CMD_PREFIX + payload
    return msg + checksum(msg)


class SymaMSGs:
    INIT = b"\x00"
    IDLE = _c("808080802020202000550f")
    POWER_TOGGLE = _c("808080802020202010652f")
    LAND = _c("8080808020202020085d1f")
    LIFT = _c("808080802020206000958f")
    CALIBRATE = _c("808080802020202020754f")
