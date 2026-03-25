#!/usr/bin/env python3
"""
FPV System Watchdog
Моніторить критичні сервіси. Якщо сервіс не піднявся за 30с → reboot.
Також моніторить пінг до оператора і шле в Telegram якщо >500ms.
"""

import subprocess
import time
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("watchdog")

WATCH_SERVICES   = ["video_stream", "rc_control"]
CHECK_INTERVAL   = 10        # секунд між перевірками
FAIL_THRESHOLD   = 3         # скільки поспіль невдач → reboot (3×10=30с)
PING_HOST        = os.environ.get("OPERATOR_VPN_IP", "10.0.0.2")
PING_INTERVAL    = 30        # секунд між ping перевірками
PING_WARN_MS     = 500       # поріг попередження (мс)
PING_FAIL_COUNT  = 3         # скільки поспіль поганих пінгів → Telegram

TG_TOKEN  = ""
TG_CHATID = ""

# Завантажити з fpv.env
def load_env():
    global TG_TOKEN, TG_CHATID, PING_HOST
    try:
        with open("/etc/fpv/fpv.env") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TG_TOKEN="):
                    TG_TOKEN = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("TG_CHAT_ID="):
                    TG_CHATID = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("OPERATOR_HOST="):
                    PING_HOST = line.split("=", 1)[1].strip().strip('"')
    except Exception as e:
        log.warning("Cannot load fpv.env: %s", e)


def tg_send(msg: str):
    if not TG_TOKEN or not TG_CHATID:
        return
    try:
        subprocess.run([
            "curl", "-s", "-X", "POST",
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            "-d", f"chat_id={TG_CHATID}",
            "-d", f"text={msg}",
            "-d", "parse_mode=HTML",
        ], timeout=5, capture_output=True)
    except Exception:
        pass


def is_service_active(name: str) -> bool:
    r = subprocess.run(
        ["systemctl", "is-active", name],
        capture_output=True, text=True)
    return r.stdout.strip() == "active"


def restart_service(name: str):
    subprocess.run(["systemctl", "restart", name], timeout=10)


def ping_ms(host: str) -> float | None:
    """Повертає час пінгу в мс або None якщо недоступний."""
    try:
        r = subprocess.run(
            ["ping", "-c", "1", "-W", "1", host],
            capture_output=True, text=True, timeout=3)
        if r.returncode != 0:
            return None
        for line in r.stdout.splitlines():
            if "time=" in line:
                return float(line.split("time=")[1].split()[0])
    except Exception:
        pass
    return None


def do_reboot(reason: str):
    log.critical("REBOOT: %s", reason)
    tg_send(f"🔄 <b>Pi перезавантажується</b>\nПричина: {reason}")
    time.sleep(2)
    subprocess.run(["reboot"])


def main():
    load_env()
    log.info("Watchdog started | services=%s | ping_host=%s",
             WATCH_SERVICES, PING_HOST)
    tg_send("👁 <b>Watchdog запущено</b>")

    fail_counts   = {s: 0 for s in WATCH_SERVICES}
    ping_fail_cnt = 0
    ping_warned   = False
    last_ping_check = 0.0

    while True:
        time.sleep(CHECK_INTERVAL)

        # ── Сервіси ──────────────────────────────────────────────────────────
        for svc in WATCH_SERVICES:
            if is_service_active(svc):
                if fail_counts[svc] > 0:
                    log.info("Service %s recovered", svc)
                fail_counts[svc] = 0
            else:
                fail_counts[svc] += 1
                log.warning("Service %s DOWN (%d/%d)", svc, fail_counts[svc], FAIL_THRESHOLD)
                if fail_counts[svc] >= FAIL_THRESHOLD:
                    do_reboot(f"{svc} не відповідає {FAIL_THRESHOLD * CHECK_INTERVAL}с")

        # ── Ping monitor ─────────────────────────────────────────────────────
        now = time.monotonic()
        if now - last_ping_check >= PING_INTERVAL:
            last_ping_check = now
            ms = ping_ms(PING_HOST)
            if ms is None:
                ping_fail_cnt += 1
                log.warning("Ping to %s FAILED (%d)", PING_HOST, ping_fail_cnt)
                if ping_fail_cnt >= PING_FAIL_COUNT and not ping_warned:
                    tg_send(f"⚠️ <b>Немає зв'язку з оператором</b>\n"
                            f"Пінг до {PING_HOST} не відповідає {ping_fail_cnt} рази поспіль")
                    ping_warned = True
            elif ms > PING_WARN_MS:
                ping_fail_cnt += 1
                log.warning("High ping: %.0f ms (%d)", ms, ping_fail_cnt)
                if ping_fail_cnt >= PING_FAIL_COUNT and not ping_warned:
                    tg_send(f"⚠️ <b>Високий пінг до оператора</b>\n"
                            f"Пінг: <b>{ms:.0f} мс</b> (поріг {PING_WARN_MS} мс)")
                    ping_warned = True
            else:
                if ping_fail_cnt > 0:
                    log.info("Ping recovered: %.0f ms", ms)
                    if ping_warned:
                        tg_send(f"✅ Зв'язок з оператором відновлено ({ms:.0f} мс)")
                ping_fail_cnt = 0
                ping_warned = False


if __name__ == "__main__":
    main()
