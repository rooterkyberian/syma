import operator
from functools import reduce

MSG_LEN = 27
IDLE = bytes.fromhex("436d640001001200010404000a000000808080802020202000550f")
CMD_PREFIX = IDLE[:-11]
_CHECKSUM0_INIT = 0x55
_PAYLOAD_DATA_START = 16


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


class SymaMSGs:
    INIT = b"\x00"
    IDLE = _c("808080802020202000550f")
    POWER_TOGGLE = _c("808080802020202010652f")
    LAND = _c("8080808020202020085d1f")
    LIFT = _c("808080802020206000958f")
    CALIBRATE = _c("808080802020202020754f")
