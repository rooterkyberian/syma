import pathlib
import struct

from syma.video import parse_frame

CAPTURE = pathlib.Path(__file__).parent / "data" / "video_datagrams.bin"


def captured_datagrams() -> list[bytes]:
    """Six consecutive datagrams the drone sent, each prefixed with its u32 length."""
    raw = CAPTURE.read_bytes()
    datagrams = []
    offset = 0
    while offset < len(raw):
        (length,) = struct.unpack_from("<I", raw, offset)
        datagrams.append(raw[offset + 4 : offset + 4 + length])
        offset += 4 + length
    return datagrams


def test_parses_captured_frames():
    frames = [parse_frame(d) for d in captured_datagrams()]
    assert [f.keyframe for f in frames] == [True, False, False, False, False, True]
    assert [f.sequence for f in frames] == [116, 117, 118, 119, 120, 121]
    assert {(f.width, f.height) for f in frames} == {(640, 480)}
    assert all(f.data.startswith(b"\x00\x00\x00\x01") for f in frames)
    # 25 fps camera clock, in microseconds
    assert frames[1].timestamp_us - frames[0].timestamp_us == 40_000


def test_keyframe_starts_with_sps_and_predicted_frame_with_slice():
    key, predicted = (parse_frame(d) for d in captured_datagrams()[:2])
    assert key.data[4] & 0x1F == 7
    assert predicted.data[4] & 0x1F == 1


def test_rejects_everything_else():
    datagram = captured_datagrams()[0]
    assert parse_frame(b"") is None
    assert parse_frame(b"\x00") is None
    assert parse_frame(b"\x00" + datagram[1:]) is None
    assert parse_frame(datagram[:-1]) is None  # truncated
    assert parse_frame(datagram[:48]) is None
