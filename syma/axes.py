"""Convert stick deflections (-1.0 .. 1.0) to the drone's axis bytes.

Throttle is a plain offset around 0x80. The other three axes are
sign-magnitude: the low 7 bits hold the deflection and the top bit holds
the direction, so 0x7F and 0xFF are the two extremes and 0x80 is neutral.
"""

from syma import NEUTRAL

_MAX_MAGNITUDE = 0x7F
_DIRECTION_BIT = 0x80


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _sign_magnitude(value: float, positive_sets_bit: bool) -> int:
    value = _clamp(value)
    magnitude = round(abs(value) * _MAX_MAGNITUDE)
    if magnitude == 0:
        return NEUTRAL
    if (value > 0) == positive_sets_bit:
        return _DIRECTION_BIT | magnitude
    return magnitude


def throttle_byte(value: float) -> int:
    """-1.0 = full down, 0.0 = hold altitude, 1.0 = full up."""
    return max(0, min(255, NEUTRAL + round(_clamp(value) * _MAX_MAGNITUDE)))


def elevator_byte(value: float) -> int:
    """Positive = forward."""
    return _sign_magnitude(value, positive_sets_bit=False)


def rudder_byte(value: float) -> int:
    """Positive = rotate right."""
    return _sign_magnitude(value, positive_sets_bit=True)


def aileron_byte(value: float) -> int:
    """Positive = strafe right."""
    return _sign_magnitude(value, positive_sets_bit=True)
