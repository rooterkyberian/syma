"""QObject exposing the drone to QML.

The asyncio-based SymaController runs on its own thread; results come back
to the GUI thread through a queued signal, so QML only ever sees property
changes made on the GUI thread.
"""

import asyncio
import threading

from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QImage

from syma import axes, build_command
from syma.controller import SymaController
from syma_app import net
from syma_app.video import VideoDecoder

DEFAULT_ROUTE_LABEL = "System default route"


def _interface_entry(interface: net.Interface) -> dict:
    details = []
    if interface.ssid:
        details.append(interface.ssid)
    details.append(interface.ipv4 or "no address")
    return {
        "name": interface.name,
        "label": f"{interface.name}  ·  {'  ·  '.join(details)}",
        "wifi": interface.wifi,
        "onDrone": interface.on_drone_network,
    }


class DroneBridge(QObject):
    interfacesChanged = Signal()
    connectedChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    packetChanged = Signal()
    linkChanged = Signal()
    videoChanged = Signal()
    #: a picture from the drone's camera; a null image when the video ends
    frameReady = Signal(QImage)

    _event = Signal(str, object)
    _decoded = Signal(QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._interfaces: list[dict] = []
        self._preferred_index = 0
        self._connected = False
        self._busy = False
        self._status = "Disconnected"
        self._sticks = (0.0, 0.0, 0.0, 0.0)
        self._packet = ""
        self._update_packet()

        self._drone: SymaController | None = None
        self._rx_seen = 0
        self._rx_rate = -1
        self._interface = None
        self._reachable = False
        self._frames_seen = 0
        self._video_fps = 0
        self._decoded.connect(self._on_decoded, Qt.ConnectionType.QueuedConnection)
        self._decoder = VideoDecoder(self._decoded.emit)
        self._link_timer = QTimer(self)
        self._link_timer.setInterval(1000)
        self._link_timer.timeout.connect(self._poll_link)
        self._link_timer.start()
        self._session = None
        self._event.connect(self._on_event, Qt.ConnectionType.QueuedConnection)

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="syma-io", daemon=True
        )
        self._thread.start()

    # -- properties -------------------------------------------------------

    @Property("QVariantList", notify=interfacesChanged)
    def interfaces(self):
        return self._interfaces

    @Property(int, notify=interfacesChanged)
    def preferredIndex(self):
        return self._preferred_index

    @Property(bool, notify=connectedChanged)
    def connected(self):
        return self._connected

    @Property(bool, notify=busyChanged)
    def busy(self):
        """A connection attempt is under way (joining Wi-Fi, opening the link)."""
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(str, notify=packetChanged)
    def packet(self):
        return self._packet

    @Property(bool, notify=linkChanged)
    def reachable(self):
        """Whether the drone answers on the network while we are connected."""
        return self._reachable

    @Property(int, notify=linkChanged)
    def rxRate(self):
        """Packets per second coming back from the drone; -1 while disconnected."""
        return self._rx_rate

    @Property(int, notify=videoChanged)
    def videoFps(self):
        """Camera pictures shown during the last second."""
        return self._video_fps

    # -- slots called from QML ---------------------------------------------

    @Slot()
    def refreshInterfaces(self):
        self._run_blocking("interfaces", net.list_interfaces)

    @Slot(str)
    def connectDrone(self, interface):
        """Join the drone's Wi-Fi on `interface` if it is not there yet, then connect."""
        if self._session is not None:
            return
        self._set_busy(True)
        self._set_status("Connecting…")
        self._interface = interface or None
        self._session = asyncio.run_coroutine_threadsafe(
            self._run_session(interface or None), self._loop
        )

    @Slot()
    def disconnectDrone(self):
        if self._session is not None:
            self._session.cancel()

    @Slot(float, float, float, float)
    def setSticks(self, throttle, rudder, elevator, aileron):
        """All values -1.0 .. 1.0; positive = up / right / forward / right."""
        self._sticks = (throttle, rudder, elevator, aileron)
        drone = self._drone
        if drone is not None:
            self._apply_sticks(drone)
        self._update_packet()

    @Slot()
    def takeoff(self):
        self._command("takeoff")

    @Slot()
    def land(self):
        self._command("land")

    @Slot()
    def calibrate(self):
        self._command("calibrate")

    @Slot()
    def emergencyStop(self):
        self._command("emergency_stop")

    @Slot()
    def shutdown(self):
        self._link_timer.stop()
        if self._session is not None:
            self._session.cancel()
            try:
                self._session.result(timeout=1)
            except BaseException:  # noqa: BLE001 - cancellation or timeout, both fine here
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=1)
        self._decoder.close()

    # -- worker thread -----------------------------------------------------

    def _run_blocking(self, kind, fn):
        def work():
            try:
                self._event.emit(kind, fn())
            except Exception as e:  # noqa: BLE001 - surfaced in the status line
                self._event.emit("error", str(e))

        self._loop.call_soon_threadsafe(self._loop.run_in_executor, None, work)

    async def _run_session(self, interface):
        drone = None
        try:
            await self._ensure_drone_wifi(interface)
            drone = SymaController(interface=interface)
            self._apply_sticks(drone)
            self._decoder.reset()
            drone.on_video = self._decoder.feed
            await drone.connect()
            self._drone = drone
            self._event.emit("connected", interface)
            await drone.wait()
        except asyncio.CancelledError:
            self._event.emit("disconnected", "Disconnected")
        except net.NetError as e:
            self._event.emit("disconnected", f"Connection failed: {e}")
        except OSError as e:
            self._event.emit("disconnected", f"Connection failed: {e.strerror or e}")
        finally:
            self._drone = None
            if drone is not None:
                await drone.disconnect()

    async def _ensure_drone_wifi(self, interface):
        if not interface:
            return
        loop = asyncio.get_running_loop()
        if not await loop.run_in_executor(None, net.needs_drone_wifi, interface):
            return
        self._event.emit(
            "status", f"Looking for {net.DRONE_SSID_PREFIX}* Wi-Fi on {interface}…"
        )
        ssid = await loop.run_in_executor(None, net.join_drone_wifi, interface)
        self._event.emit("status", f"Joined {ssid}, connecting…")
        self._event.emit(
            "interfaces", await loop.run_in_executor(None, net.list_interfaces)
        )

    def _command(self, name, *args):
        drone = self._drone
        if drone is not None:
            asyncio.run_coroutine_threadsafe(getattr(drone, name)(*args), self._loop)

    def _apply_sticks(self, drone):
        throttle, rudder, elevator, aileron = self._sticks
        drone.throttle = axes.throttle_byte(throttle)
        drone.rudder = axes.rudder_byte(rudder)
        drone.elevator = axes.elevator_byte(elevator)
        drone.aileron = axes.aileron_byte(aileron)

    # -- GUI thread --------------------------------------------------------

    @Slot(str, object)
    def _on_event(self, kind, payload):
        if kind == "interfaces":
            self._interfaces = [_interface_entry(i) for i in payload]
            self._interfaces.append(
                {
                    "name": "",
                    "label": DEFAULT_ROUTE_LABEL,
                    "wifi": False,
                    "onDrone": False,
                }
            )
            names = [i["name"] for i in self._interfaces]
            on_drone = [n for n, i in enumerate(self._interfaces) if i["onDrone"]]
            if self._session is not None and (self._interface or "") in names:
                # keep the selection on the interface the session is using
                self._preferred_index = names.index(self._interface or "")
            else:
                self._preferred_index = on_drone[0] if on_drone else 0
            self.interfacesChanged.emit()
        elif kind == "status":
            self._set_status(payload)
        elif kind == "connected":
            self._set_busy(False)
            self._set_connected(True)
            self._set_status(f"Connected via {payload or DEFAULT_ROUTE_LABEL.lower()}")
        elif kind == "disconnected":
            self._session = None
            self._set_busy(False)
            self._set_connected(False)
            self._set_status(payload)
            self.frameReady.emit(QImage())
        elif kind == "error":
            self._set_status(payload)

    @Slot(QImage)
    def _on_decoded(self, image):
        if self._connected:  # the decoder may still be busy after a disconnect
            self._frames_seen += 1
            self.frameReady.emit(image)

    def _poll_link(self):
        drone = self._drone
        if drone is None:
            rate = -1
            self._rx_seen = 0
        else:
            rate = drone.rx_packets - self._rx_seen
            self._rx_seen = drone.rx_packets
        reachable = drone is not None and net.drone_reachable(self._interface)
        if rate != self._rx_rate or reachable != self._reachable:
            self._rx_rate = rate
            self._reachable = reachable
            self.linkChanged.emit()
        fps, self._frames_seen = self._frames_seen, 0
        if fps != self._video_fps:
            self._video_fps = fps
            self.videoChanged.emit()

    def _set_connected(self, value):
        if value != self._connected:
            self._connected = value
            self.connectedChanged.emit()

    def _set_busy(self, value):
        if value != self._busy:
            self._busy = value
            self.busyChanged.emit()

    def _set_status(self, value):
        if value != self._status:
            self._status = value
            self.statusChanged.emit()

    def _update_packet(self):
        throttle, rudder, elevator, aileron = self._sticks
        packet = build_command(
            throttle=axes.throttle_byte(throttle),
            elevator=axes.elevator_byte(elevator),
            rudder=axes.rudder_byte(rudder),
            aileron=axes.aileron_byte(aileron),
        )
        text = packet[16:].hex(" ")
        if text != self._packet:
            self._packet = text
            self.packetChanged.emit()
