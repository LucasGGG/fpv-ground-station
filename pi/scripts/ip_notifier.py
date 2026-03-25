#!/usr/bin/env python3
"""
IP Notifier + WireGuard endpoint auto-update
- Відправляє в Telegram поточний IP при запуску і при зміні
- При зміні публічного IP — автоматично оновлює Endpoint в fpv0.conf і рестартує VPN
"""

import os
import time
import socket
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ip_notifier")

BOT_TOKEN      = os.environ.get("TG_TOKEN",    "8749302922:AAF68P1QHX5P9Dgtjq7TLTx-5EzELT4vaA4")
CHAT_ID        = os.environ.get("TG_CHAT_ID",  "6249172445")
WG_CONF        = os.environ.get("WG_CONF",     "/etc/wireguard/fpv0.conf")
WG_IFACE       = os.environ.get("WG_IFACE",    "fpv0")
WG_PORT        = os.environ.get("WG_PORT",     "51820")
CHECK_INTERVAL = 60


def send_telegram(text: str):
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
    }).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
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


def get_wg_endpoint() -> str:
    """Читає поточний Endpoint з fpv0.conf."""
    try:
        with open(WG_CONF) as f:
            for line in f:
                if line.strip().startswith("Endpoint"):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def update_wg_endpoint(new_ip: str) -> bool:
    """Оновлює Endpoint в fpv0.conf і перезапускає WireGuard."""
    try:
        new_endpoint = f"{new_ip}:{WG_PORT}"
        r = subprocess.run(
            ["sed", "-i", f"s|^Endpoint = .*|Endpoint = {new_endpoint}|", WG_CONF],
            capture_output=True, timeout=5)
        if r.returncode != 0:
            log.error("sed failed: %s", r.stderr.decode())
            return False
        # Оновити endpoint без рестарту через wg set
        subprocess.run(
            ["wg", "set", WG_IFACE, "peer", get_operator_pubkey(),
             "endpoint", new_endpoint],
            timeout=5)
        log.info("WireGuard endpoint updated: %s", new_endpoint)
        return True
    except Exception as e:
        log.error("WG update error: %s", e)
        return False


def get_operator_pubkey() -> str:
    """Читає PublicKey піра з fpv0.conf."""
    try:
        with open(WG_CONF) as f:
            in_peer = False
            for line in f:
                if line.strip() == "[Peer]":
                    in_peer = True
                elif in_peer and line.strip().startswith("PublicKey"):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def main():
    log.info("IP Notifier started")

    for _ in range(30):
        if get_local_ip() != "unknown":
            break
        time.sleep(2)

    local_ip  = get_local_ip()
    public_ip = get_public_ip()

    send_telegram(
        f"🟢 <b>FPV Ground Station запущено</b>\n"
        f"🏠 Локальний IP: <code>{local_ip}</code>\n"
        f"🌐 Публічний IP: <code>{public_ip}</code>\n"
        f"📡 WG endpoint: <code>{get_wg_endpoint()}</code>"
    )

    prev_local  = local_ip
    prev_public = public_ip

    while True:
        time.sleep(CHECK_INTERVAL)
        new_local  = get_local_ip()
        new_public = get_public_ip()

        changed = new_local != prev_local or new_public != prev_public
        if not changed:
            continue

        log.info("IP changed: local %s→%s, public %s→%s",
                 prev_local, new_local, prev_public, new_public)

        # Якщо змінився публічний IP — оновити WireGuard endpoint
        wg_updated = ""
        if new_public != prev_public and new_public != "unknown":
            ok = update_wg_endpoint(new_public)
            wg_updated = (
                f"\n✅ WireGuard endpoint оновлено: <code>{new_public}:{WG_PORT}</code>"
                if ok else
                f"\n❌ WireGuard endpoint НЕ оновлено (помилка)"
            )

        send_telegram(
            f"🔄 <b>IP змінився!</b>\n"
            f"🏠 Локальний: <code>{new_local}</code> (було: <code>{prev_local}</code>)\n"
            f"🌐 Публічний: <code>{new_public}</code> (було: <code>{prev_public}</code>)"
            + wg_updated
        )
        prev_local  = new_local
        prev_public = new_public


if __name__ == "__main__":
    main()
