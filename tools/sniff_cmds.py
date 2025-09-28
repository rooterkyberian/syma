#!python

"""
Colorful readout of commands from pcap(ng) file
"""

import datetime
import operator
import pathlib
import queue
import subprocess
from functools import reduce
from io import StringIO
from itertools import zip_longest

import fire
from scapy.layers.dot11 import RadioTap
from scapy.layers.inet import UDP
from scapy.packet import Raw
from scapy.sendrecv import AsyncSniffer
from scapy.themes import DefaultTheme

color_theme = DefaultTheme()


def sniff_gen(**kwargs):
    pkts = queue.SimpleQueue()
    t = AsyncSniffer(store=False, prn=pkts.put, **kwargs)
    t.start()
    try:
        while True:
            yield pkts.get()
    except KeyboardInterrupt:
        pass
    t.stop()


def _read_cmds_from_pcap(stream):
    for pkt in stream:
        if isinstance(pkt, Raw):
            pkt = RadioTap(pkt)
        if UDP in pkt:
            dgram = pkt[UDP]
            if dgram.dport == 5555:
                yield dgram


def dedup(gen, key=lambda x: x):
    sentinel = prev = object()
    for e in gen:
        e_key = key(e)
        if prev is sentinel or prev != e_key:
            yield e
            prev = e_key


def bytesdiff(a: bytes, b: bytes) -> str:
    buf = StringIO()
    for a1, b1 in zip_longest(a, b[: len(a)]):
        color = color_theme.green if a1 == b1 else color_theme.red
        buf.write(color(f"{a1:02x}"))
    return buf.getvalue()


def setup_monitor(iface: str):
    here = pathlib.Path(__file__).parent
    subprocess.check_call([str(here / "setup_monitor.sh"), iface])


def sniff_cmds(iface: str = None, offline: str = None):
    if iface:
        setup_monitor(iface)
    pkts_stream = sniff_gen(offline=offline, iface=iface)
    dgrams = _read_cmds_from_pcap(pkts_stream)

    prefix = None
    prev = b""
    for dgram in dedup(dgrams, key=lambda d: bytes(d.payload)):
        dt = datetime.datetime.fromtimestamp(dgram.time)
        print(dt.strftime("%Y-%m-%d %H:%M:%S.%f"))
        payload = bytes(dgram.payload)
        if len(payload) > 1:  # skip INIT command
            if prefix is None:
                prefix = payload
            while not payload.startswith(prefix):
                prefix = prefix[:-1]

        if prefix is None:
            print(payload.hex())
        else:
            print(
                payload[: len(prefix)].hex()
                + bytesdiff(payload[len(prefix) :], prev[len(prefix) :])
            )

        b9 = 0x00
        b10 = reduce(operator.add, payload[:-1], b9) & 0xFF
        expected_checksum = bytes((b9, b10))
        if expected_checksum == payload[-2:]:
            print("Correct checksum")
        else:
            print(
                color_theme.red(
                    f"Incorrect checksum, expected {expected_checksum.hex()}"
                )
            )
        prev = payload


if __name__ == "__main__":
    fire.Fire(sniff_cmds)
