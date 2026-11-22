# syma
Syma X22W hacking

## Setup

    mise install
    uv sync
    source .venv/bin/activate

## Usage

    # to read commands from pcap
    python tools/sniff_cmds.py --offline dumps/syma_x22w_basic_cmds.pcapng

    # or sniff some new ones

## Layout

* `syma/` - library, responsible solely for the drone protocol: building command
  packets (`syma`), stick encoding (`syma.axes`), the video framing (`syma.video`)
  and a UDP client (`syma.controller`)
* `app/` - `syma-app`, a PySide6/QML desktop app for flying the drone, built on the library
* `tools/` - sniffing / jamming scripts

## Flying the drone

    uv sync --all-packages
    uv run --package syma-app syma-app

Pick the network interface that should talk to the drone, then **Connect**.
All drone traffic is bound to that interface, so the drone can sit on a second
(e.g. USB) Wi-Fi card while your main one stays on the internet.
If the selected card is a Wi-Fi card that is not on the drone's network yet,
**Connect** first joins the drone's `FPV_*` network through NetworkManager,
without making it the default route.

Sticks can be dragged with the mouse, or use the keyboard: `W`/`S` throttle,
`A`/`D` rudder, arrow keys elevator/aileron, `R`/`F` arm, `T` take off, `L` land,
`C` calibrate, `Space`/`Esc` emergency stop.

The camera's live view sits between the sticks and starts by itself once the drone
answers; it is decoded with [PyAV](https://pyav.org/).

The drone's lights keep flashing until it is armed: connect, then press one of the
**Arm** buttons before taking off. Like the real controller, they hold both sticks
in their bottom corners for a moment - towards each other (`R`) or apart (`F`).

To record what the official app does (e.g. to arm), put a spare Wi-Fi card into
monitor mode and watch the phone talk to the drone:

    sudo .venv/bin/python tools/capture_arming.py <interface>

## Syma X22W Hardware

Board SoCs:
* microcontroller (flight controller): STM32F031K6
* IMU: InvenSense MPU6050A - strangely enough it doesn't seem to have barometer while drone does have attitude control

Camera daughter board - Joyhonest (FPV board; Wifi RX):
* WiFi SoC: Marvell 88W8801-NMD2

Camera daughter board is connected by 3-pin cable (RX, Vcc, GND) to main board.
Based on Vcc it seems it was being powered directly from battery.

Data seems to be able only to flow from Wifi SoC to flight controller.

Potato-quality board pics:
![Syma X22W board top](./images/syma_x22w_board_top.png)
![Syma X22W board bottom](./images/syma_x22w_board_bottom.png)
![Syma X22W fpv board top](./images/syma_x22w_fpv_board_top.png)
![Syma X22W fpv board bottom](./images/syma_x22w_fpv_board_bottom.png)

## Android app

Either Syma Go or Go+ seems to work.
Decompiling [Syma Go](http://www.symatoys.com/downshow/Syma-Go-apk-download.html) with [Jadx](https://github.com/skylot/jadx) reveals following:
* presence of Joyhonest SDK indicated camera daughter board responsible for WiFi connectivity is produced by them. This makes `sources/com/joyhonest` directory the treasure trove for protocol reverse engineering efforts.
* `com.tomdxs.symago.OldlibStartActivity` contains logic for building 10-byte command packets - but as name suggests - this is likely old code for a different hardware
* per `com.tomdxs.symago.WifiStateReceiver` android app assumes
  * we are connected to a drone only if your IP is in 172.16.10.0/24 subnet or some specific subnets of 192.168.0.0/24
  * drone wifi ssid should always starts `FPV_`
* there are some mentions of RTSP - but once again it seems that was used with other drones
* among other things there are binaries such as `jh_wifi.so` which are harder to decompile and very well can contain the protocol details


## Syma X22W protocol

1. Connect to Syma Wifi
2. Client gets assigned random IP through DHCP (from 172.16.10.0/24 pool)
3. Communication then proceeds exlusively through UDP with 172.16.10.1 (drone)


UDP ports:
* 172.16.10.1:6666 -> 172.168.10.x:6666 - h264 video stream
* 172.168.10.x:6666 -> 172.16.10.1:5555 - steering commands

Command packet is always 27 Bytes, each starting with "Cmd" 3-byte preable leaving 24B for rest of the message.

From the hardware and UDP traffic it seems there is no telemetry transmitted over WiFi.

### Video stream

Once it hears commands, the drone sends 640x480 H.264 (Main profile, 25 fps, a keyframe
every ~5 frames) from its port 6666 back to the port the commands come from. As the
commands go to port 5555, a stateful firewall (ufw, firewalld) does not take the video
for a reply and drops it; `SymaController` therefore sends an empty datagram to the
drone's port 6666 every second, which makes the video part of a flow we started. Every frame is a single UDP
datagram - bigger than the MTU, so it arrives as IP fragments - made of a 48-byte
little-endian header followed by an Annex B access unit (`syma.video.parse_frame`):

```
 B  | CONTENT
  0 | magic 05 0f 0f
  3 | 51 = keyframe (SPS + PPS + IDR), 50 = predicted frame
  5 | frame counter, wraps at 256
 16 | u32 payload length
 20 | u32 timestamp in microseconds
 32 | u16 width, u16 height
 40 | u32 payload length (again), u32 0x14
 48 | H.264, starting with 00 00 00 01
```

### Sample command payloads

Following payloads should be sent over UDP from :6666 to 172.16.10.1:5555 .

The payload of the first packet is just single byte with zero:
```
init
00
```

For everything else `436d640001001200010404000a000000` seems to be a common prefix, leaving 11 bytes to work with.

```
normal
808080802020202000550f
turn off
808080802020202010652f
turn on
808080802020202010652f
land
8080808020202020085d1f
lift
808080802020206000958f
calibrate
808080802020202020754f
high rotation speed
8080808020a0202000d50f
high speed mode?
808080802020a0a000550f
```

```
IDLE
 0 1 2 3 4 5 6 7 8 910 
808080802020202000550f
RUDD TRIMMER = 1
8080808020202120005611
            ^^    ^^^^
RUDD TRIMMER = 2
8080808020202220005713
            ^^    ^^^^
AILE TRIMMER = 1
8080808020202021005611
              ^^  ^^^^
ELEV TRIMMER = 1
8080808020212020005611
          ^^      ^^^^
```

```
Bytes writeup:
 B | NAME | NORMAL | HIGH | LOW
 0 | THRO |     80 |   ff |  00
 1 | ELEV |     80 |   7f |  00
 2 | RUDD |     80 |   ff |  7f
 3 | AILE |     80 |   ff |  7f

 4 | ?
 5 | ELEV TRIM
 6 | RUDD TRIM
 7 | AILE TRIM
 8 | SPECIAL CMD?
 9 | CHECKSUM0 | 0x55 + XOR(bytes 0-8)
10 | CHECKSUM1 | Sum of all previous 26 bytes (bytes 0-9 of payload + 16-byte prefix)
```

the boundary value of 7f likely means that we are dealing with `signed char`.

### Checksum algorithm

The last 2 bytes of each 27-byte command packet form a dual-byte checksum over the preceding 25 bytes:

**CHECKSUM0** (byte 9 of payload / byte 25 of packet):
```
CHECKSUM0 = (0x55 + XOR(payload_data[0:9])) & 0xFF
```
XOR together the 9 payload data bytes (bytes 16-24 of the packet), then add the constant `0x55`.

**CHECKSUM1** (byte 10 of payload / byte 26 of packet):
```
CHECKSUM1 = sum(packet[0:26]) & 0xFF
```
Simple 8-bit sum of all 26 preceding bytes (including CHECKSUM0).
