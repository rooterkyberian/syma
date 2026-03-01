import asyncio

import asyncio_dgram

from syma import (
    DRONE_IP,
    DRONE_PORT,
    LIFT_TRIM_THROTTLE,
    LOCAL_PORT,
    NEUTRAL,
    SPECIAL_CALIBRATE,
    SPECIAL_LAND,
    SPECIAL_NONE,
    SPECIAL_POWER_TOGGLE,
    TRIM_NEUTRAL,
    SymaMSGs,
    build_command,
)


class SymaController:
    """Async controller for the Syma X22W drone.

    Usage::

        async with SymaController() as drone:
            await drone.takeoff()
            await asyncio.sleep(3)
            drone.throttle = 0xC0  # climb
            await asyncio.sleep(2)
            await drone.land()
    """

    def __init__(
        self,
        drone_ip: str = DRONE_IP,
        drone_port: int = DRONE_PORT,
        local_port: int = LOCAL_PORT,
        hz: int = 50,
    ):
        self.drone_ip = drone_ip
        self.drone_port = drone_port
        self.local_port = local_port
        self.hz = hz

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

        self._special = SPECIAL_NONE
        self._stream = None
        self._task = None

    async def connect(self):
        """Open UDP socket, send init byte, and start the command loop."""
        self._stream = await asyncio_dgram.bind(("0.0.0.0", self.local_port))
        await self._stream.send(SymaMSGs.INIT, (self.drone_ip, self.drone_port))
        self._task = asyncio.create_task(self._command_loop())

    async def disconnect(self):
        """Stop the command loop and close the socket."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def _command_loop(self):
        interval = 1.0 / self.hz
        while True:
            cmd = build_command(
                throttle=self.throttle,
                elevator=self.elevator,
                rudder=self.rudder,
                aileron=self.aileron,
                trim_elevator=self.trim_elevator,
                trim_rudder=self.trim_rudder,
                trim_aileron=self.trim_aileron,
                trim_throttle=self.trim_throttle,
                special=self._special,
            )
            await self._stream.send(cmd, (self.drone_ip, self.drone_port))
            self._special = SPECIAL_NONE
            await asyncio.sleep(interval)

    async def takeoff(self):
        """Send the lift/auto-takeoff command (one-shot)."""
        self.trim_throttle = LIFT_TRIM_THROTTLE
        # Give the drone a few ticks to receive the lift trim
        await asyncio.sleep(0.1)
        self.trim_throttle = TRIM_NEUTRAL

    async def land(self):
        """Send the land command (one-shot)."""
        self._special = SPECIAL_LAND

    async def calibrate(self):
        """Send the calibrate command (one-shot)."""
        self._special = SPECIAL_CALIBRATE

    async def emergency_stop(self):
        """Toggle power off immediately (one-shot)."""
        self._special = SPECIAL_POWER_TOGGLE

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
