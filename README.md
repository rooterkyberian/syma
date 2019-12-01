# syma
Syma X22W hacking

## Syma X22W Hardware

Board SoCs:
* microcontroller (flight controller): STM32F031K6
* IMU: InvenSense MPU6050A - strangely enough it doesn't seem to have barometer while drone does have attitude control

Camera daughter board (FPV board; Wifi RX):
* WiFi SoC: Marvell 88W8801-NMD2

Camera daughter board is connected by 3-pin cable (RX, Vcc, GND) to main board.
Based on Vcc it seems it was being powered directly from battery.

Data seems to be able only to flow from Wifi SoC to flight controller.

Potato-quality board pics:
![Syma X22W board top](./images/syma_x22w_board_top.png)
![Syma X22W board bottom](./images/syma_x22w_board_bottom.png)
![Syma X22W fpv board top](./images/syma_x22w_fpv_board_top.png)
![Syma X22W fpv board bottom](./images/syma_x22w_fpv_board_bottom.png)

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

init
00
normal
436d640001001200010404000a000000808080802020202000550f
turn off
436d640001001200010404000a000000808080802020202010652f
turn on
436d640001001200010404000a000000808080802020202010652f
land
436d640001001200010404000a0000008080808020202020085d1f
lift
436d640001001200010404000a000000808080802020206000958f
calibrate
436d640001001200010404000a000000808080802020202020754f
