#!/usr/bin/env python3
"""
UDP → CRSF RC Bridge
Receives RC control packets from operator PC via UDP,
converts to CRSF protocol, sends to ELRS TX via UART.

Packet format (operator → Pi):
  Header:  2 bytes  magic 0xRC (0x52 0x43)
  Channels: 32 bytes = 16 x uint16_t LE (values 1000-2000 us)
  Checksum: 2 bytes  sum of all channel bytes (uint16 LE)
  Total: 36 bytes

Usage:
  UART_PORT=/dev/serial0 OPERATOR_HOST=10.0.0.2 python3 rc_control.py
"""

import os
import socket
import struct
import serial
import threading
import time
import logging
import signal
import sys
from crsf import build_rc_frame, build_failsafe_frame

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("rc_bridge")

UART_PORT        = os.environ.get("UART_PORT",    "/dev/serial0")
UART_BAUD        = int(os.environ.get("UART_BAUD", "420000"))
UDP_PORT         = int(os.environ.get("RC_UDP_PORT", "5601"))
CRSF_HZ          = int(os.environ.get("CRSF_HZ",    "100"))
FAILSAFE_TIMEOUT = float(os.environ.get("FAILSAFE_TIMEOUT", "1.0"))

PACKET_MAGIC   = b'\x52\x43'
PACKET_SIZE    = 36
CHANNELS_COUNT = 16
CENTER_US      = 1500
THROTTLE_IDX   = 2   # CH3
ARM_IDX        = 4   # CH5 — SE switch (2000=armed)
ARM_DISARMED   = 1000

STATS_INTERVAL = 10.0   # log packet rate every N seconds

running = True
last_packet_time = 0.0
channel_lock = threading.Lock()
channels_us = [CENTER_US] * CHANNELS_COUNT
channels_us[THROTTLE_IDX] = ARM_DISARMED

# Stats
packets_received = 0
packets_bad = 0


def open_serial() -> serial.Serial:
    while running:
        try:
            ser = serial.Serial(UART_PORT, UART_BAUD, timeout=0)
            log.info("UART opened: %s @ %d baud", UART_PORT, UART_BAUD)
            return ser
        except serial.SerialException as e:
            log.error("UART open failed: %s — retry in 2s", e)
            time.sleep(2)


def udp_receiver():
    global last_packet_time, channels_us, packets_received, packets_bad

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1.0)
    sock.bind(("0.0.0.0", UDP_PORT))
    log.info("UDP listening on port %d", UDP_PORT)

    while running:
        try:
            data, addr = sock.recvfrom(256)
        except socket.timeout:
            continue
        except OSError:
            break

        if len(data) != PACKET_SIZE:
            packets_bad += 1
            log.debug("Bad packet size: %d from %s", len(data), addr)
            continue

        if data[:2] != PACKET_MAGIC:
            packets_bad += 1
            log.debug("Bad magic from %s", addr)
            continue

        raw_channels = data[2:34]
        checksum_recv = struct.unpack_from("<H", data, 34)[0]
        if (sum(raw_channels) & 0xFFFF) != checksum_recv:
            packets_bad += 1
            log.debug("Checksum mismatch from %s", addr)
            continue

        new_channels = [max(1000, min(2000, ch))
                        for ch in struct.unpack("<16H", raw_channels)]

        with channel_lock:
            channels_us[:] = new_channels
            last_packet_time = time.monotonic()
            packets_received += 1

    sock.close()


def make_failsafe_channels() -> list:
    """
    Failsafe values:
    - Throttle → 1000 (motors off)
    - ARM (CH5) → 1000 (disarmed)
    - Everything else → center
    """
    ch = [CENTER_US] * CHANNELS_COUNT
    ch[THROTTLE_IDX] = ARM_DISARMED
    ch[ARM_IDX] = ARM_DISARMED
    return ch


def crsf_sender():
    ser = open_serial()
    interval = 1.0 / CRSF_HZ
    in_failsafe = False
    last_stats_time = time.monotonic()
    last_stats_rx = 0

    while running:
        t_start = time.monotonic()

        now = time.monotonic()
        with channel_lock:
            age = now - last_packet_time if last_packet_time > 0 else float("inf")
            ch = list(channels_us)
            rx_count = packets_received

        if age > FAILSAFE_TIMEOUT:
            if not in_failsafe:
                log.warning("FAILSAFE ACTIVE — no packets for %.1fs (throttle=1000, arm=1000)", age)
                in_failsafe = True
            frame = build_rc_frame(make_failsafe_channels())
        else:
            if in_failsafe:
                log.info("Link recovered — resuming normal control")
                in_failsafe = False
            frame = build_rc_frame(ch)

        try:
            ser.write(frame)
        except serial.SerialException as e:
            log.error("UART write error: %s — reopening", e)
            try:
                ser.close()
            except Exception:
                pass
            ser = open_serial()

        # Periodic stats
        if now - last_stats_time >= STATS_INTERVAL:
            delta_rx = rx_count - last_stats_rx
            rate = delta_rx / STATS_INTERVAL
            arm_state = "ARMED" if ch[ARM_IDX] >= 1800 else "disarmed"
            log.info(
                "Link: %.0f pkt/s | bad=%d | thro=%d | arm=%s | age=%.2fs",
                rate, packets_bad, ch[THROTTLE_IDX], arm_state, age if age != float("inf") else -1
            )
            last_stats_time = now
            last_stats_rx = rx_count

        elapsed = time.monotonic() - t_start
        sleep_time = interval - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


def handle_signal(sig, frame):
    global running
    log.info("Signal %d — shutting down, sending failsafe...", sig)
    running = False
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT,  handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    recv_thread = threading.Thread(target=udp_receiver, daemon=True, name="udp-rx")
    recv_thread.start()

    crsf_sender()


if __name__ == "__main__":
    main()
