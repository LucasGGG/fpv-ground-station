#!/usr/bin/env python3
"""
Operator RC Sender
Reads joystick input and sends RC packets to the Pi ground station via UDP.

Packet format:
  [0x52 0x43] [ch0..ch15 uint16 LE x16] [checksum uint16 LE]
  Total: 36 bytes

Dependencies:
  pip install pygame

Usage:
  PI_HOST=10.0.0.1 python3 rc_sender.py
"""

import os
import socket
import struct
import time
import sys

PI_HOST = os.environ.get("PI_HOST", "10.0.0.1")
RC_PORT = int(os.environ.get("RC_UDP_PORT", "5601"))
SEND_HZ = int(os.environ.get("SEND_HZ", "50"))

MAGIC = b'\x52\x43'
CHANNELS = 16
CENTER_US = 1500
MIN_US    = 1000
MAX_US    = 2000

# Joystick axis mapping (update for your controller)
AXIS_MAP = {
    "roll":     0,
    "pitch":    1,
    "throttle": 2,
    "yaw":      3,
}
CH_MAP = {
    "roll":     0,
    "pitch":    1,
    "throttle": 2,
    "yaw":      3,
}
# Axes that need to be inverted (value flipped)
INVERT = {
    "throttle": False,
    "pitch":    False,
    "roll":     True,
    "yaw":      True,
}


def axis_to_us(value: float, invert: bool = False) -> int:
    """Convert pygame axis value (-1.0 to 1.0) to microseconds (1000-2000)."""
    if invert:
        value = -value
    return int((value + 1.0) / 2.0 * 1000 + 1000)


def build_packet(channels: list) -> bytes:
    raw = struct.pack("<16H", *channels)
    checksum = sum(raw) & 0xFFFF
    return MAGIC + raw + struct.pack("<H", checksum)


def main():
    try:
        import pygame
    except ImportError:
        print("ERROR: pygame not installed. Run: pip install pygame")
        sys.exit(1)

    pygame.init()
    pygame.joystick.init()

    if pygame.joystick.get_count() == 0:
        print("No joystick found. Connect a controller and retry.")
        sys.exit(1)

    joy = pygame.joystick.Joystick(0)
    joy.init()
    print(f"Using joystick: {joy.get_name()}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / SEND_HZ

    print(f"Sending RC to {PI_HOST}:{RC_PORT} at {SEND_HZ} Hz")

    try:
        while True:
            t_start = time.monotonic()
            pygame.event.pump()

            channels = [CENTER_US] * CHANNELS
            channels[CH_MAP["roll"]]     = axis_to_us(joy.get_axis(AXIS_MAP["roll"]),     invert=INVERT.get("roll",     False))
            channels[CH_MAP["pitch"]]    = axis_to_us(joy.get_axis(AXIS_MAP["pitch"]),    invert=INVERT.get("pitch",    False))
            channels[CH_MAP["throttle"]] = axis_to_us(joy.get_axis(AXIS_MAP["throttle"]), invert=INVERT.get("throttle", False))
            channels[CH_MAP["yaw"]]      = axis_to_us(joy.get_axis(AXIS_MAP["yaw"]))

            pkt = build_packet(channels)
            sock.sendto(pkt, (PI_HOST, RC_PORT))

            elapsed = time.monotonic() - t_start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()
        pygame.quit()


if __name__ == "__main__":
    main()
