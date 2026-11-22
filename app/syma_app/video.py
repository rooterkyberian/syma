"""Turn the drone's H.264 frames into pictures QML can show."""

import queue
import threading
from collections.abc import Callable

import av
from PySide6.QtCore import Property, QObject, QRectF, QSizeF, Qt, Signal, Slot
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickPaintedItem

from syma.video import VideoFrame

_RESET = object()
_STOP = object()
# ~2 s of video; more than that waiting means the decoder cannot keep up
_BACKLOG = 50


def _new_codec() -> av.CodecContext:
    codec = av.CodecContext.create("h264", "r")
    # frame threading would hold pictures back by one frame per thread
    codec.thread_type = "SLICE"
    codec.options = {"flags": "low_delay"}
    return codec


def _to_image(frame: av.VideoFrame) -> QImage:
    rgb = frame.reformat(format="rgb24")
    plane = rgb.planes[0]
    image = QImage(
        bytes(plane),
        rgb.width,
        rgb.height,
        plane.line_size,
        QImage.Format.Format_RGB888,
    )
    return image.copy()  # the QImage above only borrows the bytes


class VideoDecoder:
    """Decodes frames on its own thread, so slow pictures never delay commands.

    `on_image` is called from that thread with every decoded picture.
    """

    def __init__(self, on_image: Callable[[QImage], None]):
        self._on_image = on_image
        self._queue: queue.Queue = queue.Queue(maxsize=_BACKLOG)
        self._thread = threading.Thread(
            target=self._run, name="syma-video", daemon=True
        )
        self._thread.start()

    def feed(self, frame: VideoFrame):
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            pass  # the picture recovers at the next keyframe

    def reset(self):
        """Forget the stream so far; decoding resumes at the next keyframe."""
        self._queue.put(_RESET)

    def close(self):
        self._queue.put(_STOP)
        self._thread.join(timeout=1)

    def _run(self):
        codec = None
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            if item is _RESET:
                codec = None
                continue
            if codec is None:
                if not item.keyframe:
                    continue
                codec = _new_codec()
            try:
                pictures = codec.decode(av.Packet(item.data))
            except av.FFmpegError:
                codec = None  # damaged stream: start over at the next keyframe
                continue
            for picture in pictures:
                self._on_image(_to_image(picture))


class VideoView(QQuickPaintedItem):
    """Shows the pictures of a `source` that has a `frameReady(QImage)` signal."""

    sourceChanged = Signal()
    hasFrameChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source: QObject | None = None
        self._image = QImage()

    @Property(QObject, notify=sourceChanged)
    def source(self):
        return self._source

    @source.setter
    def source(self, source):
        if source is self._source:
            return
        if self._source is not None:
            self._source.frameReady.disconnect(self.setFrame)
        self._source = source
        if source is not None:
            source.frameReady.connect(self.setFrame)
        self.sourceChanged.emit()

    @Property(bool, notify=hasFrameChanged)
    def hasFrame(self):
        return not self._image.isNull()

    @Slot(QImage)
    def setFrame(self, image):
        """A null image clears the view."""
        had_frame = self.hasFrame
        self._image = image
        if had_frame != self.hasFrame:
            self.hasFrameChanged.emit()
        self.update()

    def paint(self, painter: QPainter):
        if self._image.isNull():
            return
        bounds = self.boundingRect()
        size = QSizeF(self._image.size()).scaled(
            bounds.size(), Qt.AspectRatioMode.KeepAspectRatio
        )
        target = QRectF(0, 0, size.width(), size.height())
        target.moveCenter(bounds.center())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, self._image)
