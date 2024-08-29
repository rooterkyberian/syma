# syma
Syma X22W hacking

## Scripting

    rye sync
    . .venv/bin/activate
    
    # to read commands from pcap
    python tools/sniff_cmds.py --offline dumps/syma_x22w_basic_cmds.pcapng
    
    # or sniff some new ones

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
 9 | CHECKSUM0 | ?
10 | CHECKSUM1 | Sum of all previous 26 bytes
```

the boundary value of 7f likely means that we are dealing with `signed char`.

Byte 9 is ???
Byte 10 is just a sum of all previous bytes.
