#!/usr/bin/env python3
"""Send one native USB-CDC control frame to Combat Robot v2.

Frame: usb control <lx> <ly> <rx> <ry> <lt> <rt> <buttons> <dpad>
Axes: -512..511; triggers: 0..1023; buttons: uint16; dpad: 0..8.
The board requires a fresh frame every 250 ms and safe-stops on timeout.
"""
import argparse, serial, time
p=argparse.ArgumentParser()
p.add_argument('--port', required=True)
p.add_argument('--lx',type=int,default=0); p.add_argument('--ly',type=int,default=0)
p.add_argument('--rx',type=int,default=0); p.add_argument('--ry',type=int,default=0)
p.add_argument('--lt',type=int,default=0); p.add_argument('--rt',type=int,default=0)
p.add_argument('--buttons',type=int,default=0); p.add_argument('--dpad',type=int,default=8)
a=p.parse_args()
frame=f'usb control {a.lx} {a.ly} {a.rx} {a.ry} {a.lt} {a.rt} {a.buttons} {a.dpad}\n'.encode()
with serial.Serial(a.port,115200,timeout=1,write_timeout=1) as s:
    s.reset_input_buffer(); s.write(frame); s.flush(); time.sleep(.05)
    print(s.read(512).decode(errors='replace').strip())
