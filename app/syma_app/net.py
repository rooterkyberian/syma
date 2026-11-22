"""Find network interfaces and put one of them on the drone's Wi-Fi.

Lets the drone live on a secondary Wi-Fi card while another interface keeps
the internet connection. Linux only: relies on sysfs, `iw` and
NetworkManager's `nmcli`.
"""

import fcntl
import ipaddress
import json
import pathlib
import shutil
import socket
import struct
import subprocess
from dataclasses import dataclass

DRONE_NETWORK = ipaddress.ip_network("172.16.10.0/24")
DRONE_IP = "172.16.10.1"
DRONE_SSID_PREFIX = "FPV_"

_SYS_NET = pathlib.Path("/sys/class/net")
_SIOCGIFADDR = 0x8915
_NMCLI_TIMEOUT = 45


class NetError(RuntimeError):
    pass


@dataclass(frozen=True)
class Interface:
    name: str
    wifi: bool
    ipv4: str | None = None
    ssid: str | None = None

    @property
    def on_drone_network(self) -> bool:
        return (
            self.ipv4 is not None and ipaddress.ip_address(self.ipv4) in DRONE_NETWORK
        )


def _ipv4_of(name: str) -> str | None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        request = struct.pack("256s", name.encode()[:15])
        try:
            reply = fcntl.ioctl(sock.fileno(), _SIOCGIFADDR, request)
        except OSError:
            return None
    return socket.inet_ntoa(reply[20:24])


def _ssid_of(name: str) -> str | None:
    iw = shutil.which("iw") or "/usr/sbin/iw"
    try:
        out = subprocess.run(
            [iw, "dev", name, "link"], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        key, _, value = line.strip().partition(": ")
        if key == "SSID":
            return value
    return None


def list_interfaces() -> list[Interface]:
    """All non-loopback interfaces, Wi-Fi ones first."""
    interfaces = []
    for _, name in socket.if_nameindex():
        if name == "lo":
            continue
        wifi = (_SYS_NET / name / "wireless").exists()
        interfaces.append(
            Interface(
                name=name,
                wifi=wifi,
                ipv4=_ipv4_of(name),
                ssid=_ssid_of(name) if wifi else None,
            )
        )
    return sorted(interfaces, key=lambda i: (not i.wifi, i.name))


def pick_drone_interface(interfaces: list[Interface]) -> Interface | None:
    """The interface already on the drone's network, if any."""
    return next((i for i in interfaces if i.on_drone_network), None)


_NEIGHBOUR_ALIVE = {"REACHABLE", "STALE", "DELAY", "PROBE", "PERMANENT"}


def drone_reachable(interface: str | None, ip: str = DRONE_IP) -> bool:
    """Whether the drone answers on the link (it resolved through ARP).

    Only meaningful while something is being sent to it: the kernel then keeps
    re-checking the neighbour and marks it failed within seconds of it going away.
    """
    cmd = ["ip", "-json", "neigh", "show", "to", ip]
    if interface:
        cmd += ["dev", interface]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
        entries = json.loads(out or "[]")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False
    return any(
        "lladdr" in entry and _NEIGHBOUR_ALIVE & set(entry.get("state", []))
        for entry in entries
    )


def needs_drone_wifi(interface: str) -> bool:
    """Whether `interface` is a Wi-Fi card that is not on the drone's network yet."""
    current = next((i for i in list_interfaces() if i.name == interface), None)
    return current is not None and current.wifi and not current.on_drone_network


def _nmcli(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["nmcli", *args], capture_output=True, text=True, timeout=_NMCLI_TIMEOUT
        )
    except FileNotFoundError as e:
        raise NetError("nmcli not found; connect to the drone Wi-Fi manually") from e
    except subprocess.TimeoutExpired as e:
        raise NetError(f"nmcli {args[0]} timed out") from e
    if proc.returncode != 0:
        raise NetError(proc.stderr.strip() or f"nmcli {args[0]} failed")
    return proc.stdout


def scan_drone_ssids(interface: str) -> list[str]:
    """SSIDs of drones visible from `interface`."""
    out = _nmcli(
        "--terse", "--escape", "no", "--fields", "SSID",
        "device", "wifi", "list", "ifname", interface, "--rescan", "yes",
    )  # fmt: skip
    return sorted({s for s in out.splitlines() if s.startswith(DRONE_SSID_PREFIX)})


def join_drone_wifi(interface: str, ssid: str | None = None) -> str:
    """Connect `interface` to the drone's (open) Wi-Fi and return its SSID.

    The connection never becomes the default route, so internet access
    through the other interfaces keeps working.
    """
    if ssid is None:
        ssids = scan_drone_ssids(interface)
        if not ssids:
            raise NetError(f"no {DRONE_SSID_PREFIX}* network visible on {interface}")
        ssid = ssids[0]

    profile = f"syma-{ssid}"
    existing = _nmcli(
        "--terse", "--escape", "no", "--fields", "NAME", "connection", "show"
    )
    if profile not in existing.splitlines():
        _nmcli(
            "connection", "add", "type", "wifi", "con-name", profile, "ssid", ssid,
            "connection.autoconnect", "no",
            "ipv4.never-default", "yes",
            "ipv6.method", "disabled",
        )  # fmt: skip
    _nmcli("connection", "up", profile, "ifname", interface)
    return ssid
