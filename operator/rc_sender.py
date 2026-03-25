#!/usr/bin/env python3
"""
Operator RC Sender — RadioMaster Boxer

Channel mapping:
  CH1  — Roll     axis 0  (right stick L/R)
  CH2  — Pitch    axis 1  (right stick U/D)
  CH3  — Throttle axis 2  (left stick U/D)
  CH4  — Yaw      axis 3  (left stick L/R)
  CH5  — SE (ARM) axis 4  (2-поз: -1→1000 disarmed / +1→2000 armed)
  CH6  — SA       axis 5  (3-поз: -1→1000 / 0→1500 / +1→2000)
  CH7  — SC       axis 6  (3-поз)
  CH8  — SF       axis 7  (2-поз)
  CH9  — SB       btn0/1  (3-поз: none→1000 / [0]→1500 / [0,1]→2000)
  CH10 — SD       btn1    (2-поз: none→1000 / [1] excl→2000)
  CH11-CH16       1500 (unused)

Usage:
  PI_HOST=10.0.0.1 python3 rc_sender.py
"""

import os
import socket
import struct
import time
import sys

PI_HOST   = os.environ.get("PI_HOST",       "10.0.0.1")
RC_PORT   = int(os.environ.get("RC_UDP_PORT", "5601"))
SEND_HZ   = int(os.environ.get("SEND_HZ",     "50"))

MAGIC     = b'\x52\x43'
CHANNELS  = 16
CENTER_US = 1500
MIN_US    = 1000
MAX_US    = 2000

# (axis_index, ch_index, invert)
STICKS = [
    (0, 0, True),    # Roll
    (1, 1, False),   # Pitch
    (2, 2, False),   # Throttle
    (3, 3, True),    # Yaw
]

# (axis_index, ch_index, label)  — 2-поз та 3-поз осьові світчі
SWITCH_AXES = [
    (4, 4, "SE"),
    (5, 5, "SA"),
    (6, 6, "SC"),
    (7, 7, "SF"),
]


def axis_to_us(value: float, invert: bool = False) -> int:
    if invert:
        value = -value
    return max(MIN_US, min(MAX_US, int((value + 1.0) / 2.0 * 1000 + 1000)))


def decode_sb_sd(btn0: int, btn1: int):
    """
    SB та SD ділять кнопки 0 і 1.
    Boxer: SB середнє і верхнє дають однаковий стан ([]) — 2 детектовані позиції.
      SB: none=1000 (up/mid), [0]=2000 (down)
      SD: [1] тільки коли btn0=0 → 2000, інакше 1000
    """
    if btn0 and btn1:
        sb = MAX_US
        sd = MIN_US
    elif btn0:
        sb = MAX_US   # SB down
        sd = MIN_US
    elif btn1:
        sb = MIN_US
        sd = MAX_US   # SD down
    else:
        sb = MIN_US
        sd = MIN_US
    return sb, sd


def build_packet(channels: list) -> bytes:
    raw      = struct.pack("<16H", *channels)
    checksum = sum(raw) & 0xFFFF
    return MAGIC + raw + struct.pack("<H", checksum)


def main():
    try:
        import pygame
    except ImportError:
        print("ERROR: pip install pygame")
        sys.exit(1)

    pygame.init()
    pygame.joystick.init()

    if pygame.joystick.get_count() == 0:
        print("No joystick found.")
        sys.exit(1)

    joy = pygame.joystick.Joystick(0)
    joy.init()
    print(f"Controller : {joy.get_name()}")
    print(f"Axes: {joy.get_numaxes()}  Buttons: {joy.get_numbuttons()}")
    print(f"Sending to : {PI_HOST}:{RC_PORT} @ {SEND_HZ} Hz")
    print(f"ARM        : SE axis4 (-1=disarmed / +1=armed)\n")

    sock     = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / SEND_HZ

    try:
        while True:
            t_start = time.monotonic()
            pygame.event.pump()

            channels = [CENTER_US] * CHANNELS

            for axis_idx, ch_idx, invert in STICKS:
                channels[ch_idx] = axis_to_us(joy.get_axis(axis_idx), invert)

            for axis_idx, ch_idx, _ in SWITCH_AXES:
                channels[ch_idx] = axis_to_us(joy.get_axis(axis_idx))

            btn0 = joy.get_button(0)
            btn1 = joy.get_button(1)
            channels[8], channels[9] = decode_sb_sd(btn0, btn1)

            sock.sendto(build_packet(channels), (PI_HOST, RC_PORT))

            print(
                f"Roll:{channels[0]}  Ptch:{channels[1]}  "
                f"Thro:{channels[2]}  Yaw:{channels[3]}  "
                f"SE:{channels[4]}  SA:{channels[5]}  "
                f"SC:{channels[6]}  SF:{channels[7]}  "
                f"SB:{channels[8]}  SD:{channels[9]}",
                end="\r"
            )

            elapsed = time.monotonic() - t_start
            sleep_t = interval - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()
        pygame.quit()


if __name__ == "__main__":
    main()
