#!/usr/bin/env python3
"""
Pi heartbeat sender for STM32 watchdog.
Sends "ALIVE\n" every second via UART to prevent watchdog reset.
Run as a systemd service alongside the main FPV services.
"""

import serial
import time
import os
import signal
import sys

UART_PORT = os.environ.get("WATCHDOG_UART", "/dev/ttyAMA1")
UART_BAUD = 115200
INTERVAL  = 1.0  # seconds

running = True

def handle_signal(sig, frame):
    global running
    running = False
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT,  handle_signal)

def main():
    while running:
        try:
            with serial.Serial(UART_PORT, UART_BAUD, timeout=1) as ser:
                print(f"Watchdog heartbeat on {UART_PORT}")
                while running:
                    ser.write(b"ALIVE\n")
                    time.sleep(INTERVAL)
        except serial.SerialException as e:
            print(f"UART error: {e}, retrying in 2s...")
            time.sleep(2)

if __name__ == "__main__":
    main()
