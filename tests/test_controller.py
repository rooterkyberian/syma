import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from syma import (
    LIFT_TRIM_THROTTLE,
    NEUTRAL,
    SPECIAL_CALIBRATE,
    SPECIAL_LAND,
    SPECIAL_POWER_TOGGLE,
    SymaMSGs,
    build_command,
)
from syma.controller import SymaController


class FakeStream:
    """Fake asyncio_dgram stream that records sent packets."""

    def __init__(self):
        self.sent = []
        self.closed = False

    async def send(self, data, addr):
        self.sent.append((data, addr))

    def close(self):
        self.closed = True


@pytest.fixture
def fake_stream():
    return FakeStream()


@pytest.fixture
def controller(fake_stream):
    with patch("syma.controller.asyncio_dgram") as mock_dgram:
        mock_dgram.bind = AsyncMock(return_value=fake_stream)
        ctrl = SymaController(hz=100)
        ctrl._mock_dgram = mock_dgram
        yield ctrl


@pytest.mark.asyncio
async def test_connect_sends_init(controller, fake_stream):
    await controller.connect()
    try:
        assert fake_stream.sent[0] == (SymaMSGs.INIT, ("172.16.10.1", 5555))
    finally:
        await controller.disconnect()


@pytest.mark.asyncio
async def test_disconnect_closes_stream(controller, fake_stream):
    await controller.connect()
    await controller.disconnect()
    assert fake_stream.closed


@pytest.mark.asyncio
async def test_context_manager(controller, fake_stream):
    async with controller:
        assert controller._stream is not None
    assert fake_stream.closed
    assert controller._stream is None


@pytest.mark.asyncio
async def test_background_loop_sends_idle(controller, fake_stream):
    await controller.connect()
    try:
        await asyncio.sleep(0.05)
        # Should have sent init + at least one idle command
        commands = [data for data, _addr in fake_stream.sent[1:]]
        assert len(commands) >= 1
        assert commands[0] == SymaMSGs.IDLE
    finally:
        await controller.disconnect()


@pytest.mark.asyncio
async def test_land_sets_special(controller, fake_stream):
    await controller.connect()
    try:
        await controller.land()
        await asyncio.sleep(0.05)
        commands = [data for data, _addr in fake_stream.sent[1:]]
        land_cmd = build_command(special=SPECIAL_LAND)
        assert land_cmd in commands
    finally:
        await controller.disconnect()


@pytest.mark.asyncio
async def test_special_auto_clears(controller, fake_stream):
    await controller.connect()
    try:
        await controller.land()
        await asyncio.sleep(0.05)
        # After the land tick, subsequent commands should be idle
        commands = [data for data, _addr in fake_stream.sent[1:]]
        land_cmd = build_command(special=SPECIAL_LAND)
        idle_cmd = SymaMSGs.IDLE
        land_idx = commands.index(land_cmd)
        # At least one idle after the land
        assert idle_cmd in commands[land_idx + 1 :]
    finally:
        await controller.disconnect()


@pytest.mark.asyncio
async def test_calibrate(controller, fake_stream):
    await controller.connect()
    try:
        await controller.calibrate()
        await asyncio.sleep(0.05)
        commands = [data for data, _addr in fake_stream.sent[1:]]
        assert build_command(special=SPECIAL_CALIBRATE) in commands
    finally:
        await controller.disconnect()


@pytest.mark.asyncio
async def test_emergency_stop(controller, fake_stream):
    await controller.connect()
    try:
        await controller.emergency_stop()
        await asyncio.sleep(0.05)
        commands = [data for data, _addr in fake_stream.sent[1:]]
        assert build_command(special=SPECIAL_POWER_TOGGLE) in commands
    finally:
        await controller.disconnect()


@pytest.mark.asyncio
async def test_takeoff(controller, fake_stream):
    await controller.connect()
    try:
        await controller.takeoff()
        await asyncio.sleep(0.05)
        commands = [data for data, _addr in fake_stream.sent[1:]]
        lift_cmd = build_command(trim_throttle=LIFT_TRIM_THROTTLE)
        assert lift_cmd in commands
    finally:
        await controller.disconnect()


@pytest.mark.asyncio
async def test_set_axes_clamps(controller, fake_stream):
    controller.set_axes(throttle=300, elevator=-10)
    assert controller.throttle == 255
    assert controller.elevator == 0


@pytest.mark.asyncio
async def test_set_axes_partial(controller, fake_stream):
    controller.set_axes(throttle=0xC0)
    assert controller.throttle == 0xC0
    assert controller.elevator == NEUTRAL  # unchanged


@pytest.mark.asyncio
async def test_reset_sticks(controller, fake_stream):
    controller.throttle = 0xFF
    controller.elevator = 0x00
    controller.reset_sticks()
    assert controller.throttle == NEUTRAL
    assert controller.elevator == NEUTRAL
    assert controller.rudder == NEUTRAL
    assert controller.aileron == NEUTRAL


@pytest.mark.asyncio
async def test_custom_axes_sent(controller, fake_stream):
    await controller.connect()
    try:
        controller.set_axes(throttle=0xC0, rudder=0xA0)
        await asyncio.sleep(0.05)
        commands = [data for data, _addr in fake_stream.sent[1:]]
        expected = build_command(throttle=0xC0, rudder=0xA0)
        assert expected in commands
    finally:
        await controller.disconnect()
