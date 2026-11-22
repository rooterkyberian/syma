import struct

import pytest

from syma.handshake import (
    CHALLENGE_LEN,
    RESPONSE_LEN,
    HandshakeError,
    build_response,
    validate_challenge,
)

# (challenge, response) pairs captured from the official app talking to a drone,
# with the two nonces recovered from the captured response.
CAPTURED = [
    (
        "46 8c 00 00 01 70 ff ff 5b 22 ef 3c a2 1e ef 3c 00 02 00 00",
        "01 c4 a1 14 a7 a0 0d c9 a8 64 af dd",
        (0x00A1C400, 0x10000000),
    ),
    (
        "60 a4 00 00 01 58 ff ff 2d a4 d5 bb 8e a0 d5 bb 00 02 00 00",
        "01 4c a4 16 bc 4e 6b 5c bd 9a 0f 73",
        (0x02A44C00, 0xEC000000),
    ),
]
# challenges only, from a third session
MORE_CHALLENGES = ["e0 19 00 00 01 e4 ff ff 1a 95 2a f9 fb 92 2a f9 00 02 00 00"]


def _b(hexstr):
    return bytes.fromhex(hexstr.replace(" ", ""))


@pytest.mark.parametrize("ch, resp, rand", CAPTURED)
def test_build_response_matches_official_app(ch, resp, rand):
    assert build_response(_b(ch), _rand=rand) == _b(resp)


@pytest.mark.parametrize("ch, resp, _rand", CAPTURED)
def test_validate_accepts_real_challenges(ch, resp, _rand):
    validate_challenge(_b(ch))  # must not raise


@pytest.mark.parametrize("ch", MORE_CHALLENGES)
def test_validate_accepts_more_real_challenges(ch):
    validate_challenge(_b(ch))


@pytest.mark.parametrize("ch, resp, _rand", CAPTURED)
def test_response_is_self_consistent_for_any_nonce(ch, resp, _rand):
    # the drone re-derives and checks these relations; they must hold for any nonce
    out = build_response(_b(ch), _rand=(0xDEADBEEF, 0x12345678))
    assert len(out) == RESPONSE_LEN
    r0, r1, r2 = struct.unpack("<3I", out)
    assert r2 == (r0 + r1) & 0xFFFFFFFF
    w0 = struct.unpack("<5I", _b(ch))[0]
    from syma.handshake import CLIENT_ID_KEY

    decoded = CLIENT_ID_KEY[(r0 >> 10) & 0x3F] ^ r1
    assert (decoded >> 18) & 0xFF == CLIENT_ID_KEY[w0 & 0x3F] & 0xFF


def test_bad_checksum_rejected():
    bad = bytearray(_b(CAPTURED[0][0]))
    bad[8] ^= 0xFF
    with pytest.raises(HandshakeError):
        validate_challenge(bytes(bad))


def test_wrong_length_rejected():
    with pytest.raises(HandshakeError):
        validate_challenge(b"\x00" * 10)
    assert CHALLENGE_LEN == 20
