from unittest.mock import patch

import pytest

from syma_app import net


def test_on_drone_network():
    assert net.Interface("wlan1", True, "172.16.10.42").on_drone_network
    assert not net.Interface("wlan0", True, "192.168.1.5").on_drone_network
    assert not net.Interface("wlan2", True).on_drone_network


def test_pick_drone_interface():
    home = net.Interface("wlan0", True, "192.168.1.5")
    drone = net.Interface("wlan1", True, "172.16.10.42")
    assert net.pick_drone_interface([home, drone]) is drone
    assert net.pick_drone_interface([home]) is None


def test_scan_keeps_only_drone_ssids():
    with patch.object(net, "_nmcli", return_value="home\nFPV_b\n\nFPV_a\nFPV_a\n"):
        assert net.scan_drone_ssids("wlan1") == ["FPV_a", "FPV_b"]


def test_join_creates_profile_that_never_becomes_default_route():
    calls = []

    def fake_nmcli(*args):
        calls.append(args)
        return "home\n" if "show" in args else ""

    with patch.object(net, "_nmcli", side_effect=fake_nmcli):
        assert net.join_drone_wifi("wlan1", "FPV_a") == "FPV_a"

    add = next(c for c in calls if c[:2] == ("connection", "add"))
    assert add[add.index("ipv4.never-default") + 1] == "yes"
    assert add[add.index("ssid") + 1] == "FPV_a"
    assert calls[-1] == ("connection", "up", "syma-FPV_a", "ifname", "wlan1")


def test_join_reuses_existing_profile():
    calls = []

    def fake_nmcli(*args):
        calls.append(args)
        return "syma-FPV_a\n" if "show" in args else ""

    with patch.object(net, "_nmcli", side_effect=fake_nmcli):
        net.join_drone_wifi("wlan1", "FPV_a")

    assert not any(c[:2] == ("connection", "add") for c in calls)


def test_join_without_visible_drone_fails():
    with patch.object(net, "_nmcli", return_value="home\n"):
        with pytest.raises(net.NetError):
            net.join_drone_wifi("wlan1")


def test_only_wifi_cards_off_the_drone_network_need_joining():
    interfaces = [
        net.Interface("wlan0", True, "192.168.1.5", "home"),
        net.Interface("wlan1", True, "172.16.10.42", "FPV_a"),
        net.Interface("wlan2", True),
        net.Interface("eth0", False, "10.0.0.2"),
    ]
    with patch.object(net, "list_interfaces", return_value=interfaces):
        assert net.needs_drone_wifi("wlan0")
        assert net.needs_drone_wifi("wlan2")
        assert not net.needs_drone_wifi("wlan1")
        assert not net.needs_drone_wifi("eth0")
        assert not net.needs_drone_wifi("gone0")


@pytest.mark.parametrize(
    "output, expected",
    [
        (
            '[{"dst":"172.16.10.1","lladdr":"14:6b:9c:58:75:07","state":["REACHABLE"]}]',
            True,
        ),
        (
            '[{"dst":"172.16.10.1","lladdr":"14:6b:9c:58:75:07","state":["DELAY"]}]',
            True,
        ),
        ('[{"dst":"172.16.10.1","state":["INCOMPLETE"]}]', False),
        ('[{"dst":"172.16.10.1","state":["FAILED"]}]', False),
        ("[]", False),
        ("", False),
    ],
)
def test_drone_reachable_reads_neighbour_state(output, expected):
    with patch.object(net.subprocess, "run") as run:
        run.return_value.stdout = output
        assert net.drone_reachable("wlan1") is expected
        assert run.call_args.args[0][-2:] == ["dev", "wlan1"]
