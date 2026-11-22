import asyncio
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syma import (
    LIFT_TRIM_THROTTLE,
    MSG_LEN,
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
        self.incoming = []
        self.closed = False
        self.socket = MagicMock()

    async def send(self, data, addr):
        self.sent.append((data, addr))

    async def recv(self):
        if self.incoming:
            return self.incoming.pop(), ("172.16.10.1", 6666)
        await asyncio.Event().wait()

    def close(self):
        self.closed = True


@pytest.fixture
def fake_stream():
    return FakeStream()


@pytest.fixture
def controller(fake_stream):
    with patch("syma.controller.asyncio_dgram") as mock_dgram:
        mock_dgram.bind = AsyncMock(return_value=fake_stream)
        ctrl = SymaController(hz=100, command_hold=0.02, auto_arm=False)
        ctrl._mock_dgram = mock_dgram
        yield ctrl


@pytest.mark.asyncio
async def test_connect_streams_commands_without_init_byte(controller, fake_stream):
    await controller.connect()
    try:
        await asyncio.sleep(0.02)
        # the official app sends no init byte; every packet is a full command
        assert all(len(data) == MSG_LEN for data, _addr in fake_stream.sent)
        assert fake_stream.sent[0] == (build_command(), ("172.16.10.1", 5555))
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


@pytest.mark.asyncio
async def test_connect_binds_socket_to_interface(fake_stream):
    with (
        patch("syma.controller.asyncio_dgram") as mock_dgram,
        patch("syma.controller.socket.socket") as mock_socket,
    ):
        mock_dgram.from_socket = AsyncMock(return_value=fake_stream)
        ctrl = SymaController(hz=100, interface="wlan1", auto_arm=False)
        await ctrl.connect()
        try:
            await asyncio.sleep(0.02)
            sock = mock_socket.return_value
            sock.setsockopt.assert_called_once_with(
                socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"wlan1\0"
            )
            sock.bind.assert_called_once_with(("0.0.0.0", 6666))
            mock_dgram.from_socket.assert_awaited_once_with(sock)
            assert fake_stream.sent[0] == (build_command(), ("172.16.10.1", 5555))
        finally:
            await ctrl.disconnect()


@pytest.mark.asyncio
async def test_wait_raises_when_command_loop_fails(controller, fake_stream):
    await controller.connect()

    async def failing_send(data, addr):
        raise OSError("network is down")

    fake_stream.send = failing_send
    with pytest.raises(OSError):
        await controller.wait()
    await controller.disconnect()


@pytest.mark.asyncio
async def test_special_is_held_for_command_hold(fake_stream):
    with patch("syma.controller.asyncio_dgram") as mock_dgram:
        mock_dgram.bind = AsyncMock(return_value=fake_stream)
        ctrl = SymaController(hz=100, command_hold=0.05, auto_arm=False)
        await ctrl.connect()
        try:
            await ctrl.land()
            await asyncio.sleep(0.12)
            commands = [data for data, _addr in fake_stream.sent[1:]]
            assert commands.count(build_command(special=SPECIAL_LAND)) >= 3
            assert commands[-1] == SymaMSGs.IDLE
        finally:
            await ctrl.disconnect()


@pytest.mark.asyncio
async def test_counts_packets_received_from_drone(controller, fake_stream):
    fake_stream.incoming = [b"video", b"video", b"video"]
    await controller.connect()
    try:
        await asyncio.sleep(0.02)
        assert controller.rx_packets == 3
    finally:
        await controller.disconnect()


@pytest.mark.asyncio
async def test_video_frames_are_handed_to_callback(controller, fake_stream):
    h264 = b"\x00\x00\x00\x01\x41\x9a"
    header = bytearray(48)
    header[:4] = b"\x05\x0f\x0f\x50"
    header[16] = header[40] = len(h264)
    fake_stream.incoming = [b"not video", bytes(header) + h264]
    frames = []
    controller.on_video = frames.append
    await controller.connect()
    try:
        await asyncio.sleep(0.02)
        assert [f.data for f in frames] == [h264]
        assert controller.rx_packets == 2
    finally:
        await controller.disconnect()


@pytest.mark.asyncio
async def test_keeps_video_path_open_through_firewalls(controller, fake_stream):
    video_sock = fake_stream.socket.dup.return_value
    with patch("syma.controller.VIDEO_KEEPALIVE", 0.03):
        await controller.connect()
        try:
            await asyncio.sleep(0.1)
            # empty datagrams to the port the video comes from, on the command socket
            assert 2 <= video_sock.sendto.call_count <= 5
            video_sock.sendto.assert_called_with(b"", ("172.16.10.1", 6666))
            assert all(len(data) == MSG_LEN for data, _addr in fake_stream.sent)
        finally:
            await controller.disconnect()
    video_sock.close.assert_called_once()
