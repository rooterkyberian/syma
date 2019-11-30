# syma
Syma X22W hacking

## Syma X22W Hardware

Board SoCs:
* microcontroller: STM32F031K6
* IMU: InvenSense
* wifi: ?


Potato-quality board pics:
![Syma X22W board top](./images/syma_x22w_board_top.png)
![Syma X22W board bottom](./images/syma_x22w_board_bottom.png)

## Syma X22W protocol

1. Connect to Syma Wifi
2. Client gets assigned random IP through DHCP (from 172.16.10.0/24 pool)
3. Communication then proceeds exlusively through UDP with 172.16.10.1 (drone)


UDP ports:
* 172.16.10.1:6666 -> 172.168.10.x:6666 - h264 video stream
* 172.168.10.x:6666 -> 172.16.10.1:5555 - steering commands

Command packet is always 27 Bytes, each starting with "Cmd" 3-byte preable leaving 24B for rest of the message.
