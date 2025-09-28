import operator
from functools import reduce

MSG_LEN = 27
IDLE = bytes.fromhex("436d640001001200010404000a000000808080802020202000550f")
CMD_PREFIX = IDLE[:-11]


def _c(cmd: str) -> bytes:
    data = bytes.fromhex(cmd)
    assert len(data) == MSG_LEN - len(CMD_PREFIX)
    return CMD_PREFIX + data


def checksum(msg: bytes) -> bytes:
    msg = msg[: MSG_LEN - 2]
    b9 = reduce(operator.xor, msg, 0xB9) & 0xFF
    b10 = reduce(operator.add, msg, b9) & 0xFF
    return bytes((b9, b10))


class SymaMSGs:
    INIT = b"\x00"
    IDLE = _c("808080802020202000550f")
    POWER_TOGGLE = _c("808080802020202010652f")
    LAND = _c("8080808020202020085d1f")
    LIFT = _c("808080802020206000958f")
    CALIBRATE = _c("808080802020202020754f")
