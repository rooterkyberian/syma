import asyncio
import os
import pathlib
import queue
import struct
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from syma_app import bridge as bridge_module
from syma_app import net
from syma_app.__main__ import create_engine
from syma_app.bridge import DroneBridge
from syma_app.video import VideoDecoder, VideoView

CAPTURE = pathlib.Path(__file__).parents[2] / "tests" / "data" / "video_datagrams.bin"


@pytest.fixture(scope="module")
def app():
    QQuickStyle.setStyle("Fusion")
    return QGuiApplication.instance() or QGuiApplication([])


@pytest.fixture
def bridge(app):
    bridge = DroneBridge()
    yield bridge
    bridge.shutdown()


def test_qml_loads(bridge):
    warnings = []
    engine = create_engine(bridge)
    engine.warnings.connect(warnings.extend)
    assert engine.rootObjects()
    QGuiApplication.processEvents()
    assert not warnings


def test_sticks_are_encoded_into_packet(bridge):
    assert bridge.packet == "80 80 80 80 20 20 20 20 00 55 0f"
    bridge.setSticks(1.0, -1.0, 1.0, 1.0)
    assert bridge.packet.startswith("ff 7f 7f ff ")


def test_drone_interface_is_preselected(bridge):
    bridge._on_event(
        "interfaces",
        [
            net.Interface("wlan0", True, "192.168.1.5", "home"),
            net.Interface("wlan1", True, "172.16.10.42", "FPV_a"),
        ],
    )
    assert [i["name"] for i in bridge.interfaces] == ["wlan0", "wlan1", ""]
    assert bridge.preferredIndex == 1


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        QGuiApplication.processEvents()
        time.sleep(0.005)


class FakeController:
    """Stands in for SymaController: connects at once, stays up until cancelled."""

    rx_packets = 0

    def __init__(self, interface=None):
        self.interface = interface

    async def connect(self):
        pass

    async def wait(self):
        await asyncio.Event().wait()

    async def disconnect(self):
        pass


@pytest.fixture
def fake_drone(monkeypatch):
    monkeypatch.setattr(bridge_module, "SymaController", FakeController)
    monkeypatch.setattr(net, "drone_reachable", lambda interface: True)


def test_connect_joins_drone_wifi_first(bridge, fake_drone, monkeypatch):
    joined = []
    monkeypatch.setattr(net, "needs_drone_wifi", lambda interface: True)
    monkeypatch.setattr(
        net, "join_drone_wifi", lambda interface: joined.append(interface) or "FPV_a"
    )
    monkeypatch.setattr(
        net, "list_interfaces", lambda: [net.Interface("wlan1", True, "172.16.10.42")]
    )

    bridge.connectDrone("wlan1")
    assert bridge.busy
    wait_for(lambda: bridge.connected)
    assert joined == ["wlan1"]
    assert not bridge.busy

    bridge.disconnectDrone()
    wait_for(lambda: not bridge.connected)


def test_connect_reports_missing_drone_wifi(bridge, monkeypatch):
    def no_drone(interface):
        raise net.NetError("no FPV_* network visible on wlan1")

    monkeypatch.setattr(net, "needs_drone_wifi", lambda interface: True)
    monkeypatch.setattr(net, "join_drone_wifi", no_drone)

    bridge.connectDrone("wlan1")
    wait_for(lambda: not bridge.busy)
    assert not bridge.connected
    assert bridge.status == "Connection failed: no FPV_* network visible on wlan1"


def test_connect_skips_wifi_when_already_on_drone_network(
    bridge, fake_drone, monkeypatch
):
    monkeypatch.setattr(net, "needs_drone_wifi", lambda interface: False)
    monkeypatch.setattr(
        net, "join_drone_wifi", lambda interface: pytest.fail("must not join")
    )

    bridge.connectDrone("wlan1")
    wait_for(lambda: bridge.connected)
    bridge.disconnectDrone()
    wait_for(lambda: not bridge.connected)


def test_keyboard_deflects_sticks(bridge):
    engine = create_engine(bridge)
    window = engine.rootObjects()[0]
    window.requestActivate()
    QTest.qWaitForWindowActive(window)

    QTest.keyPress(window, Qt.Key.Key_W)
    QTest.keyPress(window, Qt.Key.Key_Left)
    QGuiApplication.processEvents()
    # default keyboard deflection is 50%: throttle up, aileron left
    assert bridge.packet.startswith("c0 80 80 40 ")

    QTest.keyRelease(window, Qt.Key.Key_W)
    QTest.keyRelease(window, Qt.Key.Key_Left)
    QGuiApplication.processEvents()
    assert bridge.packet == "80 80 80 80 20 20 20 20 00 55 0f"


def captured_frames():
    from syma.video import parse_frame

    raw = CAPTURE.read_bytes()
    offset = 0
    while offset < len(raw):
        (length,) = struct.unpack_from("<I", raw, offset)
        yield parse_frame(raw[offset + 4 : offset + 4 + length])
        offset += 4 + length


def test_decoder_turns_captured_frames_into_pictures():
    pictures = queue.SimpleQueue()
    decoder = VideoDecoder(pictures.put)
    try:
        frames = list(captured_frames())
        for frame in frames[1:5]:  # no keyframe yet: nothing to show
            decoder.feed(frame)
        decoder.reset()
        for frame in frames:
            decoder.feed(frame)
        images = [pictures.get(timeout=5) for _ in frames]
    finally:
        decoder.close()
    assert pictures.empty()
    assert {(i.width(), i.height()) for i in images} == {(640, 480)}
    # a real picture, not a blank one
    assert len({images[-1].pixel(x, 240) for x in range(0, 640, 16)}) > 4


def test_video_reaches_the_view_only_while_connected(bridge):
    engine = create_engine(bridge)
    view = engine.rootObjects()[0].findChild(VideoView)
    image = QImage(640, 480, QImage.Format.Format_RGB888)
    image.fill(Qt.GlobalColor.red)

    bridge._on_decoded(image)
    assert not view.property("hasFrame")

    bridge._on_event("connected", "wlan1")
    bridge._on_decoded(image)
    assert view.property("hasFrame")
    bridge._poll_link()
    assert bridge.videoFps == 1

    bridge._on_event("disconnected", "Disconnected")
    assert not view.property("hasFrame")
