#!/usr/bin/env python3
"""
CRSF packet generator for ExpressLRS / TBS Crossfire protocol.

Supports:
  - RC_CHANNELS_PACKED frame (type 0x16) — 16 ch x 11-bit packed
  - CRC8 with poly 0xD5 (CRSF standard)
"""

import struct
from typing import List

CRSF_SYNC_BYTE = 0xC8
CRSF_FRAMETYPE_RC_CHANNELS = 0x16
CRSF_MAX_CHANNEL_VALUE = 2011
CRSF_MIN_CHANNEL_VALUE = 172
CRSF_CENTER_VALUE = 992

# Maps microseconds 1000-2000 to CRSF units 172-1811
def us_to_crsf(us: int) -> int:
    us = max(1000, min(2000, us))
    return int((us - 1000) / 1000 * (1811 - 172) + 172)


def crc8_dvb_s2(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0xD5) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def pack_channels(channels: List[int]) -> bytes:
    """Pack 16 channels (CRSF units 0-2047) into 22 bytes (11 bits each)."""
    if len(channels) < 16:
        channels = channels + [CRSF_CENTER_VALUE] * (16 - len(channels))
    channels = [max(0, min(2047, c)) for c in channels[:16]]

    bits = 0
    for i, ch in enumerate(channels):
        bits |= (ch & 0x7FF) << (i * 11)

    result = bytearray(22)
    for i in range(22):
        result[i] = (bits >> (i * 8)) & 0xFF
    return bytes(result)


def build_rc_frame(channels_us: List[int]) -> bytes:
    """
    Build a complete CRSF RC_CHANNELS_PACKED frame.

    Frame structure:
      [sync] [len] [type] [22 bytes payload] [crc]
      Total: 26 bytes
    """
    crsf_channels = [us_to_crsf(us) for us in channels_us]
    payload = pack_channels(crsf_channels)

    # len = type(1) + payload(22) + crc(1) = 24
    frame_type = bytes([CRSF_FRAMETYPE_RC_CHANNELS])
    length = len(frame_type) + len(payload) + 1  # +1 for crc

    header = bytes([CRSF_SYNC_BYTE, length])
    crc_data = frame_type + payload
    crc = crc8_dvb_s2(crc_data)

    return header + crc_data + bytes([crc])


def build_failsafe_frame() -> bytes:
    """Send failsafe: throttle low (ch3=1000), everything else centered."""
    channels = [1500] * 16
    channels[2] = 1000  # throttle channel (ch3, index 2)
    return build_rc_frame(channels)


if __name__ == "__main__":
    frame = build_rc_frame([1500] * 16)
    print(f"RC frame ({len(frame)} bytes): {frame.hex()}")
    fs = build_failsafe_frame()
    print(f"Failsafe frame: {fs.hex()}")
