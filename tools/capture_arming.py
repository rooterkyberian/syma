#!python
"""
Capture what the official app does to arm the drone.

Puts a spare Wi-Fi card into monitor mode on the drone's channel, saves every
frame exchanged with the drone to a pcap and prints a live timeline of the
commands (and anything else) the phone sends. Your main Wi-Fi card is not
touched, so you stay online.

    sudo .venv/bin/python tools/capture_arming.py wlx00c0ca000000

Procedure:
  1. power the drone on, start this script and wait for "listening"
  2. connect the phone to the drone's FPV_* Wi-Fi and open the Syma app
  3. do whatever makes the lights stop flashing, then take off and land
  4. press Ctrl-C

A status line is printed every few seconds. "drone beacons" must keep growing
(the card hears the drone) and "commands" must start growing once the app is
open on the phone - if they do not, the capture will be empty.

To look at an existing capture again:

    python tools/capture_arming.py --offline dumps/arming_....pcap
"""

import datetime
import os
import pathlib
import re
import subprocess
import sys
import time

import fire
from scapy.layers.dhcp import DHCP
from scapy.layers.dot11 import (
    Dot11,
    Dot11AssoReq,
    Dot11AssoResp,
    Dot11Auth,
    Dot11Beacon,
    Dot11Deauth,
    Dot11Disas,
    Dot11Elt,
    Dot11ProbeResp,
    RadioTap,
)
from scapy.layers.inet import IP, TCP, UDP
from scapy.packet import Raw
from scapy.sendrecv import AsyncSniffer
from scapy.utils import PcapReader, PcapWriter

from syma import DRONE_IP, DRONE_PORT, MSG_LEN, checksum

SSID_PREFIX = "FPV_"
DRONE_NET_PREFIX = "172.16.10."
VIDEO_PORT = 6666
DNS_PORT = 53
PAYLOAD_START = 16
RETRY_FLAG = 0x08
STATUS_INTERVAL = 5

RED = "\033[31m"
GREEN = "\033[32m"
DIM = "\033[2m"
RESET = "\033[0m"

_MGMT_EVENTS = {
    Dot11Auth: "auth",
    Dot11AssoReq: "association request",
    Dot11AssoResp: "association response",
    Dot11Deauth: "deauth",
    Dot11Disas: "disassociation",
}


def _run(*cmd: str, check: bool = True) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise SystemExit(f"{' '.join(cmd)} failed: {proc.stderr.strip()}")
    return proc.stdout


def find_drone(iface: str, attempts: int = 5) -> tuple[str, str, int]:
    """Scan for the drone's access point; returns (ssid, bssid, frequency in MHz)."""
    for _ in range(attempts):
        out = _run("iw", "dev", iface, "scan", check=False)
        bssid = freq = None
        for line in out.splitlines():
            if m := re.match(r"BSS ([0-9a-f:]{17})", line):
                bssid, freq = m.group(1), None
            elif m := re.match(r"\s+freq: (\d+)", line):
                freq = int(m.group(1))
            elif m := re.match(r"\s+SSID: (.*)", line):
                if m.group(1).startswith(SSID_PREFIX) and bssid and freq:
                    return m.group(1), bssid, freq
        time.sleep(2)
    raise SystemExit(
        f"no {SSID_PREFIX}* network found from {iface}; is the drone powered on? "
        "(or pass --freq, e.g. --freq 2412 for channel 1)"
    )


class Monitor:
    """Context manager: interface in monitor mode on `freq`, restored on exit."""

    def __init__(self, iface: str, freq: int | None):
        self.iface = iface
        self.freq = freq
        self.bssid = None

    def __enter__(self):
        # keep NetworkManager from fighting over the card while we use it
        _run("nmcli", "device", "set", self.iface, "managed", "no", check=False)
        _run("ip", "link", "set", self.iface, "up")
        if self.freq is None:
            ssid, self.bssid, self.freq = find_drone(self.iface)
            print(f"found {ssid} ({self.bssid}) on {self.freq} MHz")
        _run("ip", "link", "set", self.iface, "down")
        _run("iw", "dev", self.iface, "set", "type", "monitor")
        _run("ip", "link", "set", self.iface, "up")
        _run("iw", "dev", self.iface, "set", "freq", str(self.freq))
        return self

    def __exit__(self, *exc):
        _run("ip", "link", "set", self.iface, "down", check=False)
        _run("iw", "dev", self.iface, "set", "type", "managed", check=False)
        _run("nmcli", "device", "set", self.iface, "managed", "yes", check=False)


def _hex_diff(data: bytes, prev: bytes | None) -> str:
    out = []
    for n, byte in enumerate(data):
        changed = prev is not None and (n >= len(prev) or prev[n] != byte)
        out.append(f"{RED}{byte:02x}{RESET}" if changed else f"{byte:02x}")
    return " ".join(out)


class Timeline:
    """Turns sniffed frames into a readable log of what the phone asked the drone to do."""

    def __init__(self, bssid: str | None = None):
        self.bssids = {bssid} if bssid else set()
        self.t0 = None
        self.on_air = 0
        self.beacons = 0
        self.signal = None
        self.frames = 0
        self.commands = 0
        self.video_packets = 0
        self._beacon_saved = 0.0
        self.flows: dict[tuple, int] = {}
        self._cmd = None
        self._cmd_since = 0.0
        self._cmd_count = 0
        self._last_time = 0.0

    def _log(self, t: float, text: str):
        print(f"[{t - self.t0:8.2f}s] {text}", flush=True)

    def _involves_drone(self, pkt) -> bool:
        dot11 = pkt.getlayer(Dot11)
        if dot11 is not None and self.bssids & {dot11.addr1, dot11.addr2, dot11.addr3}:
            return True
        return IP in pkt and (
            pkt[IP].src.startswith(DRONE_NET_PREFIX)
            or pkt[IP].dst.startswith(DRONE_NET_PREFIX)
        )

    def _on_beacon(self, pkt) -> bool:
        """Track the drone's beacons; returns True for the ones worth saving."""
        elt = pkt.getlayer(Dot11Elt)
        if elt is None or elt.ID != 0:
            return False
        ssid = elt.info.decode(errors="replace")
        bssid = pkt[Dot11].addr3
        t = float(pkt.time)
        if bssid not in self.bssids:
            if not ssid.startswith(SSID_PREFIX):
                return False
            self.bssids.add(bssid)
            self._log(t, f"drone access point {ssid} ({bssid})")
        self.beacons += 1
        self.signal = getattr(pkt.getlayer(RadioTap), "dBm_AntSignal", None)
        if t - self._beacon_saved < 1.0:
            return False
        self._beacon_saved = t
        return True

    def status(self) -> str:
        signal = f" at {self.signal} dBm" if self.signal is not None else ""
        return (
            f"{self.on_air} frames on air, {self.beacons} drone beacons{signal}, "
            f"{self.frames} frames to/from the drone, {self.commands} commands"
        )

    def _flush_cmd(self):
        if self._cmd is not None and self._cmd_count > 1:
            held = self._last_time - self._cmd_since
            print(f"{DIM}{'':12}held {held:.2f}s, {self._cmd_count} packets{RESET}")

    def _on_command(self, t: float, data: bytes):
        self.commands += 1
        if data == self._cmd:
            self._cmd_count += 1
            self._last_time = t
            return
        self._flush_cmd()
        if len(data) == MSG_LEN:
            prev = (
                self._cmd[PAYLOAD_START:]
                if self._cmd and len(self._cmd) == MSG_LEN
                else None
            )
            text = "cmd  " + _hex_diff(data[PAYLOAD_START:], prev)
            if checksum(data[:-2]) != data[-2:]:
                text += f"  {RED}bad checksum{RESET}"
        else:
            text = f"{GREEN}cmd  unusual length {len(data)}: {data.hex(' ')}{RESET}"
        self._log(t, text)
        self._cmd, self._cmd_since, self._cmd_count, self._last_time = data, t, 1, t

    def _on_other(self, t: float, pkt):
        ip = pkt[IP]
        l4 = pkt.getlayer(UDP) or pkt.getlayer(TCP)
        proto = "udp" if UDP in pkt else "tcp" if TCP in pkt else f"ip proto {ip.proto}"
        ports = (l4.sport, l4.dport) if l4 is not None else (None, None)
        key = (ip.src, ports[0], ip.dst, ports[1], proto)
        payload = bytes(l4.payload) if l4 is not None else bytes(ip.payload)
        if ports[1] == DNS_PORT:
            # the phone looking for the internet; one summary line is enough
            key = (ip.src, None, ip.dst, DNS_PORT, "dns")
        elif DHCP in pkt:
            self._log(t, f"dhcp {ip.src} -> {ip.dst}")
        elif key not in self.flows:
            direction = "phone->drone" if ip.dst == DRONE_IP else "drone->phone"
            self._log(
                t,
                f"{GREEN}new {proto} flow {direction} {ip.src}:{ports[0]} -> {ip.dst}:{ports[1]}"
                f"  len {len(payload)}  {payload[:32].hex(' ')}{RESET}",
            )
        self.flows[key] = self.flows.get(key, 0) + 1

    def feed(self, pkt) -> bool:
        """Process one frame; returns True if it is worth saving."""
        if isinstance(pkt, Raw):
            pkt = RadioTap(bytes(pkt))
        dot11 = pkt.getlayer(Dot11)
        if dot11 is None:
            return False
        t = float(pkt.time)
        if self.t0 is None:
            self.t0 = t
        self.on_air += 1

        if pkt.haslayer(Dot11Beacon) or pkt.haslayer(Dot11ProbeResp):
            return self._on_beacon(pkt)
        if not self._involves_drone(pkt):
            return False
        self.frames += 1

        for layer, name in _MGMT_EVENTS.items():
            if pkt.haslayer(layer):
                self._log(t, f"wifi {name} {dot11.addr2} -> {dot11.addr1}")
                return True
        if IP not in pkt or dot11.FCfield & RETRY_FLAG:
            return True

        if pkt[IP].frag:
            # tail of a fragmented video packet; it has no UDP header of its own
            self.video_packets += 1
            return True
        udp = pkt.getlayer(UDP)
        if udp is not None and udp.dport == DRONE_PORT and pkt[IP].dst == DRONE_IP:
            self._on_command(t, bytes(udp.payload))
        elif udp is not None and udp.sport == VIDEO_PORT and pkt[IP].src == DRONE_IP:
            self.video_packets += 1
        else:
            self._on_other(t, pkt)
        return True

    def summary(self):
        self._flush_cmd()
        print(f"\n{self.status()}, {self.video_packets} video packets")
        for (src, sport, dst, dport, proto), count in self.flows.items():
            print(f"  {count:6d} x {proto} {src}:{sport} -> {dst}:{dport}")


def _default_output() -> pathlib.Path:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return pathlib.Path(__file__).parent.parent / "dumps" / f"arming_{stamp}.pcap"


def capture_arming(
    iface: str = None, offline: str = None, freq: int = None, out: str = None
):
    """
    iface: spare Wi-Fi interface to put into monitor mode (needs root)
    offline: analyse this pcap instead of capturing
    freq: drone's Wi-Fi frequency in MHz; found by scanning when omitted
    out: where to save the capture (default: dumps/arming_<timestamp>.pcap)
    """
    if offline:
        timeline = Timeline()
        with PcapReader(offline) as reader:
            for pkt in reader:
                timeline.feed(pkt)
        timeline.summary()
        return
    if not iface:
        raise SystemExit(__doc__)
    if os.geteuid() != 0:
        raise SystemExit("monitor mode needs root: run with sudo .venv/bin/python")

    path = pathlib.Path(out) if out else _default_output()
    with Monitor(iface, freq) as monitor:
        timeline = Timeline(monitor.bssid)
        writer = PcapWriter(str(path), sync=True)

        def on_frame(pkt):
            if timeline.feed(pkt):
                writer.write(pkt)

        sniffer = AsyncSniffer(iface=iface, store=False, prn=on_frame)
        sniffer.start()
        print(f"listening on {iface} ({monitor.freq} MHz), saving to {path}")
        print("connect the phone to the drone, arm it in the app, then press Ctrl-C\n")
        try:
            last_status = None
            while sniffer.running or sniffer.thread.is_alive():
                time.sleep(STATUS_INTERVAL)
                # proof of life: shows whether the card hears the drone at all
                status = timeline.status()
                if status != last_status:
                    print(f"{DIM}{'':12}{status}{RESET}", flush=True)
                last_status = status
        except KeyboardInterrupt:
            pass
        finally:
            if sniffer.running:
                sniffer.stop()
            writer.close()

    if "SUDO_UID" in os.environ and path.exists():
        os.chown(path, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))
    timeline.summary()
    print(f"\nsaved {path}")
    if not timeline.frames:
        print(
            "nothing involving the drone was seen - wrong frequency, or phone not connected?"
        )


if __name__ == "__main__":
    sys.exit(fire.Fire(capture_arming))
