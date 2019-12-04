#!/bin/bash -xe

IFACE=$1

ifconfig $IFACE down
iw dev $IFACE set type monitor
ifconfig $IFACE up
iw dev $IFACE set channel 1
iw dev $IFACE info
