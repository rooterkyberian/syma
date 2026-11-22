"""The drone's camera stream.

The drone sends one UDP datagram per video frame, from its port 6666 to the
port the commands come from. Each datagram is a 48-byte little-endian header followed by an
Annex B H.264 access unit:

    0  magic 05 0f 0f
    3  frame type: 0x51 keyframe (SPS + PPS + IDR), 0x50 predicted
    5  frame counter, wraps at 256
   16  u32 payload length
   20  u32 timestamp in microseconds
   32  u16 width, u16 height
   40  u32 payload length (again), u32 0x14
   48  H.264
"""

import struct
from dataclasses import dataclass

#: the drone port the stream is sent from
VIDEO_PORT = 6666
MAGIC = b"\x05\x0f\x0f"
HEADER_LEN = 48
_KEYFRAME = 0x51


@dataclass(frozen=True)
class VideoFrame:
    sequence: int
    keyframe: bool
    timestamp_us: int
    width: int
    height: int
    #: one Annex B H.264 access unit
    data: bytes


def parse_frame(datagram: bytes) -> VideoFrame | None:
    """Decode a datagram from the drone; None if it is not a complete video frame."""
    if len(datagram) < HEADER_LEN or not datagram.startswith(MAGIC):
        return None
    length, timestamp_us = struct.unpack_from("<II", datagram, 16)
    width, height = struct.unpack_from("<HH", datagram, 32)
    if length == 0 or len(datagram) != HEADER_LEN + length:
        return None
    return VideoFrame(
        sequence=datagram[5],
        keyframe=datagram[3] == _KEYFRAME,
        timestamp_us=timestamp_us,
        width=width,
        height=height,
        data=datagram[HEADER_LEN:],
    )
