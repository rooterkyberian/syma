import asyncio
import socket
from collections.abc import Callable

import asyncio_dgram
from asyncio_dgram import TransportClosed

from syma import (
    DRONE_IP,
    DRONE_PORT,
    LIFT_TRIM_THROTTLE,
    LOCAL_PORT,
    NEUTRAL,
    SPECIAL_CALIBRATE,
    SPECIAL_LAND,
    COMMAND_HOLD,
    COMMAND_HZ,
    SPECIAL_NONE,
    SPECIAL_POWER_TOGGLE,
    TRIM_NEUTRAL,
    build_command,
)
from syma import handshake
from syma.video import VIDEO_PORT, VideoFrame, parse_frame

#: seconds between the datagrams that keep the video path open
VIDEO_KEEPALIVE = 1.0


class SymaController:
    """Async controller for the Syma X22W drone.

    Usage::

        async with SymaController() as drone:
            await drone.takeoff()
            await asyncio.sleep(3)
            drone.throttle = 0xC0  # climb
            await asyncio.sleep(2)
            await drone.land()

    Set ``on_video`` to receive the camera's H.264 frames as they arrive.

    Pass ``interface`` (e.g. ``"wlx00c0ca000000"``) to send through a specific
    network interface instead of whatever the routing table picks.
    """

    def __init__(
        self,
        drone_ip: str = DRONE_IP,
        drone_port: int = DRONE_PORT,
        local_port: int = LOCAL_PORT,
        hz: int = COMMAND_HZ,
        command_hold: float = COMMAND_HOLD,
        interface: str | None = None,
        auto_arm: bool = True,
    ):
        self.drone_ip = drone_ip
        self.drone_port = drone_port
        self.local_port = local_port
        self.hz = hz
        self.command_hold = command_hold
        self.interface = interface
        self.auto_arm = auto_arm

        # Stick axes (0x00-0xFF, 0x80 = neutral)
        self.throttle = NEUTRAL
        self.elevator = NEUTRAL
        self.rudder = NEUTRAL
        self.aileron = NEUTRAL

        # Trims (0x00-0xFF, 0x20 = neutral)
        self.trim_elevator = TRIM_NEUTRAL
        self.trim_rudder = TRIM_NEUTRAL
        self.trim_aileron = TRIM_NEUTRAL
        self.trim_throttle = TRIM_NEUTRAL

        self._held: dict[str, tuple[int, float]] = {}
        self._stream = None
        self._task = None
        self._rx_task = None
        self._arm_sock = None
        self._video_sock = None

        #: whether the arming handshake succeeded; the drone only flies when True
        self.armed = False
        #: reason arming failed, for display; None while armed or not yet tried
        self.arm_error: str | None = None

        #: datagrams received from the drone (its video stream); stays 0 if
        #: the drone does not hear us
        self.rx_packets = 0
        #: called from the event loop with every camera frame; must not block
        self.on_video: Callable[[VideoFrame], None] | None = None

    async def connect(self):
        """Open UDP socket, send init byte, and start the command loop."""
        if self.interface is None:
            self._stream = await asyncio_dgram.bind(("0.0.0.0", self.local_port))
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                # route through this interface whatever the routing table says
                sock.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_BINDTODEVICE,
                    self.interface.encode() + b"\0",
                )
                sock.bind(("0.0.0.0", self.local_port))
            except OSError:
                sock.close()
                raise
            self._stream = await asyncio_dgram.from_socket(sock)
        # The official app sends no init byte: its first packet is already a
        # full command, so the command loop below is all that is needed.
        self._video_sock = self._stream.socket.dup()
        self._task = asyncio.create_task(self._command_loop())
        self._rx_task = asyncio.create_task(self._receive_loop())
        if self.auto_arm:
            await self.arm()

    async def arm(self):
        """Complete the TCP handshake that unlocks steering (and video).

        The drone ignores commands until this succeeds and the connection it
        opens stays alive. Failure is recorded in ``arm_error`` rather than
        raised, so a session can keep trying.
        """
        if self._arm_sock is not None:
            return
        try:
            self._arm_sock = await handshake.arm(self.interface, self.drone_ip)
            self.armed = True
            self.arm_error = None
        except (OSError, asyncio.TimeoutError, handshake.HandshakeError) as e:
            self.armed = False
            self.arm_error = str(e) or e.__class__.__name__

    async def disconnect(self):
        """Stop the command loop and close the socket."""
        if self._rx_task is not None:
            self._rx_task.cancel()
            self._rx_task = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, OSError):
                # OSError: the loop had already died (link lost); wait() reports it
                pass
            self._task = None
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        if self._video_sock is not None:
            self._video_sock.close()
            self._video_sock = None
        if self._arm_sock is not None:
            self._arm_sock.close()
            self._arm_sock = None
        self.armed = False

    async def wait(self):
        """Block until the command loop stops; raises if it failed (e.g. link lost)."""
        if self._task is not None:
            await self._task

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def _receive_loop(self):
        """Take in the video the drone streams back to a client it hears."""
        try:
            while True:
                data, _addr = await self._stream.recv()
                self.rx_packets += 1
                if self.on_video is not None:
                    frame = parse_frame(data)
                    if frame is not None:
                        self.on_video(frame)
        except (OSError, TransportClosed):
            pass

    def _open_video_path(self):
        """Make the video look like a reply to something we sent.

        The drone streams from its port 6666, not from the port the commands
        go to, so a stateful firewall (ufw, firewalld) sees unsolicited
        traffic and drops it. An empty datagram to that port gives the
        firewall a flow the video belongs to. asyncio refuses to send empty
        datagrams, hence the duplicate of the socket.
        """
        try:
            self._video_sock.sendto(b"", (self.drone_ip, VIDEO_PORT))
        except BlockingIOError:
            pass  # the next one will do

    async def _command_loop(self):
        interval = 1.0 / self.hz
        loop = asyncio.get_running_loop()
        next_keepalive = loop.time()
        while True:
            if loop.time() >= next_keepalive:
                self._open_video_path()
                next_keepalive = loop.time() + VIDEO_KEEPALIVE
            fields = dict(
                throttle=self.throttle,
                elevator=self.elevator,
                rudder=self.rudder,
                aileron=self.aileron,
                trim_elevator=self.trim_elevator,
                trim_rudder=self.trim_rudder,
                trim_aileron=self.trim_aileron,
                trim_throttle=self.trim_throttle,
                special=SPECIAL_NONE,
            )
            now = loop.time()
            self._held = {k: v for k, v in self._held.items() if v[1] > now}
            fields.update({name: value for name, (value, _) in self._held.items()})
            cmd = build_command(**fields)
            await self._stream.send(cmd, (self.drone_ip, self.drone_port))
            await asyncio.sleep(interval)

    def _hold(self, seconds: float | None = None, **fields: int):
        """Override packet fields for a while, then fall back to the regular values."""
        if seconds is None:
            seconds = self.command_hold
        deadline = asyncio.get_running_loop().time() + seconds
        for name, value in fields.items():
            self._held[name] = (value, deadline)

    async def takeoff(self):
        """Send the lift/auto-takeoff command."""
        self._hold(trim_throttle=LIFT_TRIM_THROTTLE)

    async def land(self):
        """Send the land command."""
        self._hold(special=SPECIAL_LAND)

    async def calibrate(self):
        """Send the calibrate command."""
        self._hold(special=SPECIAL_CALIBRATE)

    async def emergency_stop(self):
        """Toggle power off immediately."""
        self._hold(special=SPECIAL_POWER_TOGGLE)

    def reset_sticks(self):
        """Return all axes to neutral."""
        self.throttle = NEUTRAL
        self.elevator = NEUTRAL
        self.rudder = NEUTRAL
        self.aileron = NEUTRAL

    def set_axes(
        self,
        throttle: int | None = None,
        elevator: int | None = None,
        rudder: int | None = None,
        aileron: int | None = None,
    ):
        """Set one or more axes, clamping values to 0-255."""
        if throttle is not None:
            self.throttle = max(0, min(255, throttle))
        if elevator is not None:
            self.elevator = max(0, min(255, elevator))
        if rudder is not None:
            self.rudder = max(0, min(255, rudder))
        if aileron is not None:
            self.aileron = max(0, min(255, aileron))
