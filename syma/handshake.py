"""The TCP :8888 challenge/response that arms the drone and unlocks its video.

The drone stays locked (lights flashing, ignores steering) until a client
opens a TCP connection to port 8888, answers a 20-byte challenge with a
12-byte response derived from a fixed key table, and keeps that connection
open. Completing it is what lets the drone take off; the camera stream starts
at the same time. Both directions use the same keyed transform, built around
``CLIENT_ID_KEY``.

The key table and the transform were recovered from the Joyhonest Wi-Fi
library (``liblogicWiFiLib.so``) shipped in the official Syma Go app, for the
sole purpose of interoperating with a drone one owns.

All multi-byte fields are little-endian uint32.

Challenge (drone -> client), 5 words::

    w0  header / nonce (low 16 bits)
    w1  0xffff??01 marker
    w2  obfuscated session word
    w3  checksum = (w0 + w1 + w2) mod 2**32
    w4  0x200

Response (client -> drone), 3 words::

    r0  (PROTO<<26) | (rand & 0x03fffc00) | (w1 & 0x3ff)
    r1  CLIENT_ID_KEY[(r0>>10)&0x3f] ^ r1_pre
    r2  checksum = (r0 + r1) mod 2**32

where ``r1_pre = (rand & 0xfc000000) | (CLIENT_ID_KEY[w0&0x3f]&0xff)<<18 | MARKER``.
``r1_pre`` carries a byte taken from the challenge's own ``w0``, which ties
each response to the specific challenge and stops replay.
"""

import asyncio
import secrets
import socket
import struct

DRONE_HOST = "172.16.10.1"
ARM_PORT = 8888

# 100-word key table (ClientIdKey) from liblogicWiFiLib.so
CLIENT_ID_KEY = (
    0xC8768255,
    0xE62CB67C,
    0x187504B9,
    0x38705763,
    0xA05A6F5F,
    0x78B58368,
    0x545E5EA6,
    0x74C1B3D8,
    0x6D41248F,
    0x04E3347C,
    0x718C08BB,
    0x294C294F,
    0xD165B191,
    0x207C6099,
    0x543EF2AD,
    0xE4E3DB68,
    0xF6B58F44,
    0x34ED459C,
    0x0AF09926,
    0xB32B46BD,
    0x54CA5B24,
    0x992CC9B3,
    0xAACDAC2C,
    0xCA76F891,
    0x50CA4FF6,
    0x7242B547,
    0x5C3CA4AB,
    0x5D773431,
    0x2D7B2A5A,
    0xC0DEBE06,
    0xB311D6D6,
    0x06D24D34,
    0xDA6580D0,
    0x582150C1,
    0x7C6CD39C,
    0xC0A6ED46,
    0xFC46D130,
    0x6408B5E9,
    0x04823ED7,
    0x8D284A8D,
    0x26DB814E,
    0x764CE657,
    0x87D237E8,
    0x2AAD581E,
    0xCCD8946F,
    0x477C512D,
    0xDACAD3EC,
    0xACE1E68A,
    0x57A0CCA0,
    0xDB95A8A6,
    0xEB2255F4,
    0x1116DB29,
    0x41879B85,
    0xA62D166E,
    0x3F0F7F2D,
    0x249726FB,
    0xF7996122,
    0xE8229D1B,
    0xF2B3D0F0,
    0xD317E327,
    0xCD238D6D,
    0x092C6B3B,
    0xB03D5A25,
    0x5F9D047C,
    0xD73E84AF,
    0x4B9AFC32,
    0xA25E802C,
    0x2F3DD08A,
    0xFF7F3766,
    0x26188F42,
    0x61E6C8D7,
    0x343BB8E5,
    0x11038063,
    0x7CAE7DD3,
    0xEAA651B3,
    0xA178886B,
    0x2C0330B3,
    0xA2C13856,
    0x76C2D803,
    0x939FEA50,
    0xD0950765,
    0xC6C93CBA,
    0x5FC7CDCF,
    0x2B2BC379,
    0x38B26656,
    0x0C107C33,
    0x3D2DC7E3,
    0x85F8A9A1,
    0x20BBE561,
    0xB83F838C,
    0x6FE98EDA,
    0x06775D85,
    0x47D56470,
    0x88D00BFD,
    0xDCBED22A,
    0x758912FA,
    0x204A0BF4,
    0x7FECC0B2,
    0x0455B03B,
    0x9EEA8A37,
)

CHALLENGE_LEN = 20
RESPONSE_LEN = 12
_MASK = 0xFFFFFFFF
PROTO = 5  # protocol marker in r0 bits 26-31
_MARKER = 0x801  # low-18 marker shared by both directions


class HandshakeError(ValueError):
    """The challenge was malformed or failed its key check."""


def _decode(word_index: int, obfuscated: int) -> int:
    return CLIENT_ID_KEY[word_index & 0x3F] ^ obfuscated


def validate_challenge(challenge: bytes) -> int:
    """Check a 20-byte challenge and return its decoded session word.

    Raises HandshakeError if the checksum or key check fails.
    """
    if len(challenge) != CHALLENGE_LEN:
        raise HandshakeError(
            f"challenge must be {CHALLENGE_LEN} bytes, got {len(challenge)}"
        )
    w0, w1, w2, w3, _w4 = struct.unpack("<5I", challenge)
    if (w0 + w1 + w2) & _MASK != w3:
        raise HandshakeError("challenge checksum mismatch")
    decoded = _decode(w1 >> 10, w2)
    expected = (CLIENT_ID_KEY[(w0 >> 8) & 0x3F] >> 16) & 0xFF
    if (decoded >> 18) & 0xFF != expected:
        raise HandshakeError("challenge key check failed")
    return decoded


def build_response(challenge: bytes, *, _rand: tuple[int, int] | None = None) -> bytes:
    """Return the 12-byte response that unlocks video for this challenge.

    ``_rand`` injects the two nonces for tests; production uses fresh ones.
    """
    validate_challenge(challenge)
    w0, w1, _w2, _w3, _w4 = struct.unpack("<5I", challenge)

    rand1, rand2 = (
        _rand if _rand is not None else (secrets.randbits(32), secrets.randbits(32))
    )

    r0 = (PROTO << 26) | (rand1 & 0x03FFFC00) | (w1 & 0x3FF)
    r1_pre = (rand2 & 0xFC000000) | ((CLIENT_ID_KEY[w0 & 0x3F] & 0xFF) << 18) | _MARKER
    r1 = CLIENT_ID_KEY[(r0 >> 10) & 0x3F] ^ r1_pre
    r2 = (r0 + r1) & _MASK
    return struct.pack("<3I", r0, r1, r2)


async def arm(
    interface: str | None = None,
    host: str = DRONE_HOST,
    port: int = ARM_PORT,
    timeout: float = 3.0,
) -> socket.socket:
    """Open the control channel and complete the arming handshake.

    Returns the connected TCP socket. It must stay open: if it closes, the
    drone disarms. Raises OSError, asyncio.TimeoutError or HandshakeError on
    failure; the caller owns closing the socket on success.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        if interface:
            sock.setsockopt(
                socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode() + b"\0"
            )
        loop = asyncio.get_running_loop()
        await asyncio.wait_for(loop.sock_connect(sock, (host, port)), timeout)
        challenge = await asyncio.wait_for(loop.sock_recv(sock, 64), timeout)
        await loop.sock_sendall(sock, build_response(challenge))
    except BaseException:
        sock.close()
        raise
    return sock
