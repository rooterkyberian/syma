import pytest

from syma import axes


@pytest.mark.parametrize(
    "value, expected",
    [(0.0, 0x80), (1.0, 0xFF), (-1.0, 0x01), (0.5, 0xC0), (5.0, 0xFF), (-5.0, 0x01)],
)
def test_throttle_is_offset_around_neutral(value, expected):
    assert axes.throttle_byte(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [(0.0, 0x80), (1.0, 0x7F), (-1.0, 0xFF), (0.5, 0x40), (-0.5, 0xC0), (0.001, 0x80)],
)
def test_elevator_forward_is_plain_magnitude(value, expected):
    assert axes.elevator_byte(value) == expected


@pytest.mark.parametrize("to_byte", [axes.rudder_byte, axes.aileron_byte])
@pytest.mark.parametrize(
    "value, expected",
    [(0.0, 0x80), (1.0, 0xFF), (-1.0, 0x7F), (0.5, 0xC0), (-0.5, 0x40), (-9.0, 0x7F)],
)
def test_rudder_and_aileron_right_sets_direction_bit(to_byte, value, expected):
    assert to_byte(value) == expected
