#!/usr/bin/env python3
"""
IP Notifier — відправляє в Telegram поточний IP при запуску
і при зміні зовнішнього або локального IP.
"""

import os
import time
import socket
import urllib.request
import urllib.parse
import urllib.error
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ip_notifier")

BOT_TOKEN = os.environ.get("TG_TOKEN", "8749302922:AAF68P1QHX5P9Dgtjq7TLTx-5EzELT4vaA4")
CHAT_ID   = os.environ.get("TG_CHAT_ID", "6249172445")
CHECK_INTERVAL = 60  # секунд між перевірками


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
        log.info("Telegram: sent")
    except Exception as e:
        log.error("Telegram error: %s", e)


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def get_public_ip() -> str:
    for url in ["https://api.ipify.org", "https://ifconfig.me/ip"]:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.read().decode().strip()
        except Exception:
            continue
    return "unknown"


def get_hostname() -> str:
    return socket.gethostname()


def main():
    log.info("IP Notifier started")

    # Чекаємо мережу
    for _ in range(30):
        if get_local_ip() != "unknown":
            break
        time.sleep(2)

    local_ip  = get_local_ip()
    public_ip = get_public_ip()

    msg = (
        f"🟢 <b>FPV Ground Station запущено</b>\n"
        f"🖥 Хост: <code>{get_hostname()}</code>\n"
        f"🏠 Локальний IP: <code>{local_ip}</code>\n"
        f"🌐 Публічний IP: <code>{public_ip}</code>"
    )
    send_telegram(msg)

    prev_local  = local_ip
    prev_public = public_ip

    while True:
        time.sleep(CHECK_INTERVAL)

        new_local  = get_local_ip()
        new_public = get_public_ip()

        if new_local != prev_local or new_public != prev_public:
            msg = (
                f"🔄 <b>IP змінився!</b>\n"
                f"🖥 Хост: <code>{get_hostname()}</code>\n"
                f"🏠 Локальний IP: <code>{new_local}</code> (було: <code>{prev_local}</code>)\n"
                f"🌐 Публічний IP: <code>{new_public}</code> (було: <code>{prev_public}</code>)"
            )
            send_telegram(msg)
            prev_local  = new_local
            prev_public = new_public


if __name__ == "__main__":
    main()
