import pathlib
import sys

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtQuickControls2 import QQuickStyle

from syma_app.bridge import DroneBridge
from syma_app.video import VideoView

QML_DIR = pathlib.Path(__file__).parent / "qml"

qmlRegisterType(VideoView, "SymaApp", 1, 0, "VideoView")


def create_engine(bridge: DroneBridge) -> QQmlApplicationEngine:
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("drone", bridge)
    engine.load(QML_DIR / "Main.qml")
    return engine


def main() -> int:
    QQuickStyle.setStyle("Fusion")
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Syma X22W")

    bridge = DroneBridge()
    app.aboutToQuit.connect(bridge.shutdown)
    engine = create_engine(bridge)
    if not engine.rootObjects():
        return 1
    bridge.refreshInterfaces()
    exit_code = app.exec()
    del engine  # QML must go before the bridge it binds to
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
