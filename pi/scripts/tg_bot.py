#!/usr/bin/env python3
"""
FPV Ground Station — Telegram Bot (повна версія)

Можливості:
  📊 Статус        — сервіси, IP, CPU, RAM, temp, Wi-Fi, диск
  🔧 Сервіси       — старт/стоп/рестарт
  📡 VPN           — endpoint, рестарт, ping
  📋 Логи          — journalctl
  🖥 Термінал      — shell команди
  🌐 Мережа        — ping, Starlink статус
  📹 Відео         — запис ON/OFF, список, завантаження
  📈 Графіки       — CPU temp, ping за часом
  ⚙️ Конфіг        — редагування fpv.env
  🔴 Kill switch   — вимкнути всі сервіси
  ⏹ Shutdown      — безпечне вимкнення з відліком
  ⚡ Reboot        — перезавантаження
"""

import os, time, socket, subprocess, urllib.request, urllib.parse
import json, logging, threading, shutil, glob, datetime, re

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("tg_bot")

BOT_TOKEN      = os.environ.get("TG_TOKEN",   "8749302922:AAF68P1QHX5P9Dgtjq7TLTx-5EzELT4vaA4")
CHAT_ID        = os.environ.get("TG_CHAT_ID", "6249172445")
CHECK_INTERVAL = 60
WG_CONF        = "/etc/wireguard/fpv0.conf"
FPV_ENV        = "/etc/fpv/fpv.env"
SERVICES       = ["vpn", "video_stream", "rc_control"]
RECORDINGS_DIR = "/home/pi/fpv/recordings"
ACTION_LOG     = "/home/pi/fpv/action.log"
HTTP_PORT      = 8080

os.makedirs(RECORDINGS_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# Telegram API
# ══════════════════════════════════════════════════════════════════════════════

def tg_request(method: str, params: dict) -> dict:
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(params).encode()
    req  = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error("API %s: %s", method, e); return {}


def send(text: str, reply_markup: dict = None, chat_id: str = None):
    params = {"chat_id": chat_id or CHAT_ID, "text": text[:4096], "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    tg_request("sendMessage", params)


def edit(chat_id, message_id: int, text: str, reply_markup: dict = None):
    params = {"chat_id": chat_id, "message_id": message_id,
              "text": text[:4096], "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    tg_request("editMessageText", params)


def answer_callback(cb_id: str, text: str = ""):
    tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})


def send_photo_bytes(img_bytes: bytes, caption: str = ""):
    url      = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    boundary = "fpvboundary"
    body  = f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{CHAT_ID}\r\n".encode()
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode()
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"img.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode()
    body += img_bytes
    body += f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body,
          headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        log.error("sendPhoto: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# Action log
# ══════════════════════════════════════════════════════════════════════════════

def alog(action: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(ACTION_LOG, "a") as f:
            f.write(f"[{ts}] {action}\n")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# System helpers
# ══════════════════════════════════════════════════════════════════════════════

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception: return "unknown"

def get_public_ip() -> str:
    for url in ["https://api.ipify.org", "https://ifconfig.me/ip"]:
        try:
            with urllib.request.urlopen(url, timeout=8) as r: return r.read().decode().strip()
        except Exception: continue
    return "unknown"

def service_status(name: str) -> str:
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5)
        return "🟢" if r.stdout.strip() == "active" else "🔴"
    except Exception: return "⚪"

def get_cpu_temp() -> float:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000
    except Exception: return 0.0

def get_cpu_usage() -> float:
    try:
        r = subprocess.run(["top", "-bn1"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if "Cpu" in line or "cpu" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if "id" in p and i > 0:
                        return round(100 - float(parts[i-1].replace(",", ".")), 1)
    except Exception: pass
    return 0.0

def get_ram_usage() -> tuple:
    try:
        r = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith("Mem"):
                p = line.split(); return int(p[2]), int(p[1])
    except Exception: pass
    return 0, 0

def get_disk_usage() -> tuple:
    try:
        s = shutil.disk_usage("/")
        used_pct = int(s.used / s.total * 100)
        free_gb  = round(s.free / 1024**3, 1)
        return used_pct, free_gb
    except Exception: return 0, 0

def get_wifi_signal() -> str:
    try:
        r = subprocess.run(["iwconfig", "wlan0"], capture_output=True, text=True, timeout=5)
        if "Signal level=" in r.stdout:
            return r.stdout.split("Signal level=")[1].split()[0]
    except Exception: pass
    return "N/A"

def get_uptime() -> str:
    try:
        with open("/proc/uptime") as f: secs = int(float(f.read().split()[0]))
        h, m = divmod(secs // 60, 60); d, h = divmod(h, 24)
        return f"{d}д {h}г {m}хв" if d else f"{h}г {m}хв"
    except Exception: return "N/A"

def get_wg_endpoint() -> str:
    try:
        with open(WG_CONF) as f:
            for line in f:
                if line.strip().startswith("Endpoint"): return line.split("=", 1)[1].strip()
    except Exception: pass
    return "невідомо"

def set_wg_endpoint(ep: str) -> bool:
    try:
        subprocess.run(["sed", "-i", f"s|^Endpoint = .*|Endpoint = {ep}|", WG_CONF],
                       check=True, timeout=5); return True
    except Exception as e:
        log.error("set_wg_endpoint: %s", e); return False

def run_service_cmd(action: str, service: str) -> str:
    try:
        subprocess.run(["systemctl", action, service], check=True, timeout=10)
        alog(f"service {action} {service}")
        return f"✅ {action} → {service}"
    except Exception as e: return f"❌ {e}"

def get_logs(service: str, lines: int = 20) -> str:
    try:
        r = subprocess.run(
            ["journalctl", "-u", service, f"-n{lines}", "--no-pager", "--output=short"],
            capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "Немає логів"
    except Exception as e: return str(e)

def shell_exec(cmd: str, timeout: int = 15) -> str:
    BLOCKED = ["rm -rf /", "mkfs", ":(){:|:&};:", "dd if=/dev/zero of=/dev/"]
    for b in BLOCKED:
        if b in cmd: return "⛔ Команда заблокована."
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        return out[:3500] if out else "(немає виводу)"
    except subprocess.TimeoutExpired: return f"⏱ Таймаут ({timeout}с)"
    except Exception as e: return f"❌ {e}"

def ping_host(host: str, count: int = 4) -> str:
    try:
        r = subprocess.run(["ping", "-c", str(count), "-W", "2", host],
                           capture_output=True, text=True, timeout=15)
        for line in r.stdout.strip().splitlines():
            if "rtt" in line or "round-trip" in line: return line.strip()
        return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "немає відповіді"
    except Exception as e: return str(e)

def get_ping_ms(host: str) -> float:
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", host],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if "time=" in line:
                return float(line.split("time=")[1].split()[0])
    except Exception: pass
    return -1.0

def read_env_file() -> str:
    try:
        with open(FPV_ENV) as f: return f.read()
    except Exception: return ""

def write_env_file(content: str) -> bool:
    try:
        with open(FPV_ENV, "w") as f: f.write(content); return True
    except Exception: return False

def check_starlink() -> str:
    gw = "192.168.100.1"
    r  = subprocess.run(["ping", "-c", "1", "-W", "2", gw],
                        capture_output=True, text=True, timeout=5)
    if r.returncode == 0: return f"🟢 Starlink роутер ({gw}) відповідає"
    return f"🔴 Starlink роутер ({gw}) не відповідає"


# ══════════════════════════════════════════════════════════════════════════════
# Graphs (matplotlib → PNG bytes)
# ══════════════════════════════════════════════════════════════════════════════

temp_history = []    # [(timestamp, celsius), ...]
ping_history = []    # [(timestamp, ms), ...]
MAX_HISTORY  = 60    # точок

def record_metrics():
    while True:
        now = time.time()
        temp_history.append((now, get_cpu_temp()))
        ms = get_ping_ms("8.8.8.8")
        ping_history.append((now, ms))
        if len(temp_history) > MAX_HISTORY: temp_history.pop(0)
        if len(ping_history) > MAX_HISTORY: ping_history.pop(0)
        time.sleep(60)

def make_graph(data: list, title: str, ylabel: str, color: str) -> bytes:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import io

        if not data: return b""
        times  = [(t - data[0][0]) / 60 for t, _ in data]
        values = [v for _, v in data]

        fig, ax = plt.subplots(figsize=(8, 3))
        ax.plot(times, values, color=color, linewidth=2)
        ax.fill_between(times, values, alpha=0.15, color=color)
        ax.set_title(title, fontsize=13)
        ax.set_xlabel("хв тому")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="jpeg", dpi=100)
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except ImportError:
        return b""


# ══════════════════════════════════════════════════════════════════════════════
# Video recording
# Записи робляться автоматично через video_stream.sh (ENABLE_RECORDING=1).
# Бот лише перемикає режим через fpv.env і показує файли.
# ══════════════════════════════════════════════════════════════════════════════

def is_recording_enabled() -> bool:
    try:
        with open(FPV_ENV) as f:
            for line in f:
                if line.strip().startswith("ENABLE_RECORDING"):
                    return "1" in line.split("=", 1)[1]
    except Exception: pass
    return True  # default on

def set_recording(enabled: bool) -> str:
    val = "1" if enabled else "0"
    try:
        r = subprocess.run(
            ["sed", "-i", f"s|^ENABLE_RECORDING=.*|ENABLE_RECORDING={val}|", FPV_ENV],
            capture_output=True, timeout=5)
        if r.returncode != 0:
            # Рядка немає — додаємо
            with open(FPV_ENV, "a") as f:
                f.write(f"\nENABLE_RECORDING={val}\n")
        subprocess.run(["systemctl", "restart", "video_stream"], timeout=10)
        alog(f"recording {'enabled' if enabled else 'disabled'}")
        state_str = "🔴 Запис увімкнено" if enabled else "⏹ Запис вимкнено"
        return f"{state_str}\n(video_stream перезапущено)"
    except Exception as e:
        return f"❌ Помилка: {e}"

def list_recordings() -> str:
    files = sorted(glob.glob(f"{RECORDINGS_DIR}/*.mp4"), reverse=True)
    if not files: return "Немає записів"
    local_ip = get_local_ip()
    lines = []
    for f in files[:10]:
        fname = os.path.basename(f)
        size  = os.path.getsize(f) // 1024
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime("%d.%m %H:%M")
        link  = f"http://{local_ip}:{HTTP_PORT}/{fname}"
        lines.append(f"📹 <code>{fname}</code>\n   {size} KB | {mtime}\n   🔗 <code>{link}</code>")
    return "\n\n".join(lines)

def cleanup_old_files(days: int = 3):
    cutoff = time.time() - days * 86400
    removed = 0
    for pattern in [f"{RECORDINGS_DIR}/*.mp4", f"{RECORDINGS_DIR}/*.jpg"]:
        for f in glob.glob(pattern):
            if os.path.getmtime(f) < cutoff:
                os.remove(f); removed += 1
    if removed:
        log.info("Cleanup: removed %d files older than %d days", removed, days)
        send(f"🗑 Автоочистка: видалено {removed} файлів старше {days} днів")


# ══════════════════════════════════════════════════════════════════════════════
# Keyboards
# ══════════════════════════════════════════════════════════════════════════════

def kb_main():
    return {"inline_keyboard": [
        [{"text": "📊 Статус",       "callback_data": "status"},
         {"text": "🌐 IP адреси",    "callback_data": "ip"}],
        [{"text": "🔧 Сервіси",      "callback_data": "services"},
         {"text": "📡 VPN",          "callback_data": "vpn_menu"}],
        [{"text": "📋 Логи",         "callback_data": "logs_menu"},
         {"text": "🌐 Мережа",       "callback_data": "net_menu"}],
        [{"text": "🖥 Термінал",     "callback_data": "terminal"},
         {"text": "📈 Графіки",      "callback_data": "graphs_menu"}],
        [{"text": "📹 Відео",        "callback_data": "video_menu"},
         {"text": "⚙️ Конфіг",       "callback_data": "config_menu"}],
        [{"text": "🔴 Kill Switch",  "callback_data": "killswitch_confirm"},
         {"text": "⏹ Shutdown",      "callback_data": "shutdown_confirm"}],
        [{"text": "⚡ Reboot",        "callback_data": "reboot_confirm"}],
    ]}

def kb_services():
    return {"inline_keyboard": [
        [{"text": "▶️ Старт відео",  "callback_data": "svc_start_video_stream"},
         {"text": "⏹ Стоп відео",   "callback_data": "svc_stop_video_stream"}],
        [{"text": "▶️ Старт RC",     "callback_data": "svc_start_rc_control"},
         {"text": "⏹ Стоп RC",      "callback_data": "svc_stop_rc_control"}],
        [{"text": "▶️ Старт VPN",    "callback_data": "svc_start_vpn"},
         {"text": "⏹ Стоп VPN",     "callback_data": "svc_stop_vpn"}],
        [{"text": "🔄 Рестарт всіх", "callback_data": "restart_all"}],
        [{"text": "◀️ Назад",        "callback_data": "main"}],
    ]}

def kb_vpn():
    return {"inline_keyboard": [
        [{"text": "🔄 Рестарт VPN",       "callback_data": "svc_restart_vpn"}],
        [{"text": "✏️ Змінити Endpoint",   "callback_data": "vpn_change_endpoint"}],
        [{"text": "📋 Поточний Endpoint",  "callback_data": "vpn_show_endpoint"}],
        [{"text": "📶 Ping оператора",     "callback_data": "vpn_ping"}],
        [{"text": "◀️ Назад",             "callback_data": "main"}],
    ]}

def kb_logs():
    return {"inline_keyboard": [
        [{"text": "📹 Відео",  "callback_data": "log_video_stream"},
         {"text": "🎮 RC",     "callback_data": "log_rc_control"}],
        [{"text": "🔒 VPN",    "callback_data": "log_vpn"},
         {"text": "🤖 Бот",    "callback_data": "log_tg_bot"}],
        [{"text": "📝 Дії",    "callback_data": "log_actions"}],
        [{"text": "◀️ Назад",  "callback_data": "main"}],
    ]}

def kb_net():
    return {"inline_keyboard": [
        [{"text": "📶 Ping Google",   "callback_data": "ping_8888"},
         {"text": "📶 Ping VPN",      "callback_data": "ping_operator"}],
        [{"text": "🛰 Starlink",       "callback_data": "starlink_status"}],
        [{"text": "📸 Скріншот",       "callback_data": "screenshot"}],
        [{"text": "◀️ Назад",          "callback_data": "main"}],
    ]}

def kb_graphs():
    return {"inline_keyboard": [
        [{"text": "🌡 Температура CPU",   "callback_data": "graph_temp"}],
        [{"text": "📶 Ping (matplotlib)", "callback_data": "graph_ping"}],
        [{"text": "📊 Ping текст (60хв)", "callback_data": "graph_ping_text"}],
        [{"text": "◀️ Назад",             "callback_data": "main"}],
    ]}

def kb_video():
    is_rec = is_recording_enabled()
    return {"inline_keyboard": [
        [{"text": "⏹ Вимкнути запис" if is_rec else "🔴 Увімкнути запис",
          "callback_data": "rec_stop" if is_rec else "rec_start"}],
        [{"text": "📁 Список записів",     "callback_data": "rec_list"}],
        [{"text": "🗑 Очистити старі (3д)", "callback_data": "rec_cleanup"}],
        [{"text": "◀️ Назад",              "callback_data": "main"}],
    ]}

def kb_config():
    return {"inline_keyboard": [
        [{"text": "📄 Переглянути fpv.env",  "callback_data": "cfg_view"}],
        [{"text": "✏️ Редагувати fpv.env",   "callback_data": "cfg_edit"}],
        [{"text": "◀️ Назад",               "callback_data": "main"}],
    ]}

def kb_terminal():
    return {"inline_keyboard": [
        [{"text": "📁 ls fpv",     "callback_data": "term_ls"},
         {"text": "💾 df -h",      "callback_data": "term_df"}],
        [{"text": "🌡 Temp",       "callback_data": "term_temp"},
         {"text": "📊 CPU/RAM",    "callback_data": "term_cpu"}],
        [{"text": "✏️ Своя команда","callback_data": "term_custom"}],
        [{"text": "◀️ Назад",      "callback_data": "main"}],
    ]}

def kb_confirm(yes_cb: str, label: str = "✅ Так"):
    return {"inline_keyboard": [
        [{"text": label,        "callback_data": yes_cb},
         {"text": "❌ Скасувати","callback_data": "main"}],
    ]}

def kb_back():
    return {"inline_keyboard": [[{"text": "◀️ Назад", "callback_data": "main"}]]}


# ══════════════════════════════════════════════════════════════════════════════
# Text builders
# ══════════════════════════════════════════════════════════════════════════════

def ascii_ping_graph() -> str:
    if len(ping_history) < 2:
        return "⏳ Збираю дані... (потрібно хвилину)"

    values = [v for _, v in ping_history if v >= 0]
    if not values:
        return "❌ Немає відповідей від 8.8.8.8"

    min_v  = min(values)
    max_v  = max(values)
    avg_v  = sum(values) / len(values)
    last_v = values[-1]
    rows   = 6
    cols   = min(len(ping_history), 40)
    data   = ping_history[-cols:]

    # Нормалізуємо до 0..rows
    span = max_v - min_v if max_v != min_v else 1
    def norm(v):
        if v < 0: return -1
        return int((v - min_v) / span * (rows - 1))

    lines = []
    for row in range(rows - 1, -1, -1):
        label = f"{int(min_v + span * row / (rows-1)):4d}ms │"
        bar = ""
        for _, v in data:
            n = norm(v)
            if n < 0:
                bar += "░"
            elif n == row:
                bar += "█"
            elif n > row:
                bar += "│"
            else:
                bar += " "
        lines.append(label + bar)

    lines.append("      └" + "─" * cols)
    lines.append(f"      {len(data)} точок · остання {len(data)} хв")
    lines.append(f"\n📊 Зараз: {last_v:.1f}ms  Avg: {avg_v:.1f}ms  Min: {min_v:.1f}ms  Max: {max_v:.1f}ms")

    # Оцінка якості
    if avg_v < 50:
        quality = "🟢 Відмінно"
    elif avg_v < 150:
        quality = "🟡 Добре"
    elif avg_v < 300:
        quality = "🟠 Задовільно"
    else:
        quality = "🔴 Погано"

    lines.append(f"🌐 Якість: {quality}")
    return "\n".join(lines)


def text_status() -> str:
    used_ram, total_ram = get_ram_usage()
    disk_pct, disk_free = get_disk_usage()
    temp     = get_cpu_temp()
    ping_ms  = get_ping_ms("8.8.8.8")
    temp_icon = "🔥" if temp > 75 else ("🌡" if temp > 60 else "✅")
    disk_icon = "⚠️" if disk_pct > 90 else "💾"
    ping_icon = "🔴" if ping_ms < 0 else ("🟢" if ping_ms < 100 else ("🟡" if ping_ms < 300 else "🟠"))
    ping_str  = "недоступно" if ping_ms < 0 else f"{ping_ms:.1f} ms"
    lines = ["<b>📊 Статус системи</b>\n"]
    for svc in SERVICES:
        lines.append(f"{service_status(svc)}  {svc}")
    lines += [
        f"\n🏠 Локальний IP:  <code>{get_local_ip()}</code>",
        f"🌐 Публічний IP:  <code>{get_public_ip()}</code>",
        f"{temp_icon} CPU Темп:      <code>{temp:.1f}°C</code>",
        f"⚙️ CPU:           <code>{get_cpu_usage()}%</code>",
        f"💾 RAM:           <code>{used_ram}MB / {total_ram}MB</code>",
        f"{disk_icon} Диск:          <code>{disk_pct}% (вільно {disk_free}GB)</code>",
        f"⏱ Uptime:        <code>{get_uptime()}</code>",
        f"📶 Wi-Fi:         <code>{get_wifi_signal()}</code>",
        f"{ping_icon} Ping інтернет: <code>{ping_str}</code>",
    ]
    return "\n".join(lines)

def text_ip() -> str:
    return (
        f"<b>🌐 IP адреси</b>\n\n"
        f"🏠 Локальний:    <code>{get_local_ip()}</code>\n"
        f"🌐 Публічний:    <code>{get_public_ip()}</code>\n"
        f"📡 VPN Endpoint: <code>{get_wg_endpoint()}</code>"
    )


# ══════════════════════════════════════════════════════════════════════════════
# State
# ══════════════════════════════════════════════════════════════════════════════

state = {}   # chat_id → "wait_endpoint" | "wait_cmd" | "wait_cfg"


# ══════════════════════════════════════════════════════════════════════════════
# Handlers
# ══════════════════════════════════════════════════════════════════════════════

def handle_message(msg: dict):
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text    = msg.get("text", "").strip()
    if chat_id != CHAT_ID: return

    cur = state.get(chat_id)

    if cur == "wait_endpoint":
        state.pop(chat_id)
        if ":" in text:
            ok = set_wg_endpoint(text)
            alog(f"VPN endpoint changed to {text}")
            send("✅ Endpoint змінено.\nПерезапусти VPN." if ok else "❌ Помилка.", reply_markup=kb_vpn())
        else:
            send("⚠️ Формат: <code>IP:PORT</code>", reply_markup=kb_vpn())
        return

    if cur == "wait_cmd":
        state.pop(chat_id)
        alog(f"shell: {text}")
        send(f"⌨️ <code>{text}</code>")
        send(f"<pre>{shell_exec(text)}</pre>", reply_markup=kb_terminal())
        return

    if cur == "wait_cfg":
        state.pop(chat_id)
        if write_env_file(text):
            alog("fpv.env edited via bot")
            send("✅ fpv.env збережено. Перезапусти сервіси.", reply_markup=kb_config())
        else:
            send("❌ Помилка запису файлу.", reply_markup=kb_config())
        return

    if text in ("/start", "/menu"):
        send("🚁 <b>FPV Ground Station</b>\n\nОберіть дію:", reply_markup=kb_main())
    elif text == "/status":
        send(text_status(), reply_markup=kb_main())
    elif text == "/ip":
        send(text_ip(), reply_markup=kb_main())
    elif text.startswith("/run "):
        cmd = text[5:]
        alog(f"shell: {cmd}")
        send(f"<pre>{shell_exec(cmd)}</pre>")


def handle_callback(cb: dict):
    chat_id    = str(cb.get("message", {}).get("chat", {}).get("id", ""))
    message_id = cb.get("message", {}).get("message_id")
    data       = cb.get("data", "")
    cb_id      = cb.get("id")
    if chat_id != CHAT_ID: return
    answer_callback(cb_id)

    # ── Main ──
    if data == "main":
        edit(chat_id, message_id, "🚁 <b>FPV Ground Station</b>\n\nОберіть дію:", kb_main())
    elif data == "status":
        edit(chat_id, message_id, text_status(), kb_main())
    elif data == "ip":
        edit(chat_id, message_id, text_ip(), kb_main())

    # ── Services ──
    elif data == "services":
        edit(chat_id, message_id, "🔧 <b>Керування сервісами</b>", kb_services())
    elif data.startswith("svc_"):
        parts = data.split("_", 2); action, svc = parts[1], parts[2]
        result = run_service_cmd(action, svc)
        edit(chat_id, message_id, result, kb_services())
    elif data == "restart_all":
        results = [run_service_cmd("restart", s) for s in SERVICES]
        edit(chat_id, message_id, "\n".join(results), kb_services())

    # ── VPN ──
    elif data == "vpn_menu":
        edit(chat_id, message_id, "📡 <b>VPN налаштування</b>", kb_vpn())
    elif data == "vpn_show_endpoint":
        edit(chat_id, message_id, f"📡 Endpoint:\n<code>{get_wg_endpoint()}</code>", kb_vpn())
    elif data == "vpn_change_endpoint":
        state[chat_id] = "wait_endpoint"
        edit(chat_id, message_id,
             "✏️ Введи новий Endpoint:\n<code>IP:PORT</code>\n\nПриклад: <code>31.131.99.25:51820</code>",
             kb_back())
    elif data == "vpn_ping":
        edit(chat_id, message_id, "⏳ Пінгую...")
        edit(chat_id, message_id,
             f"📶 <b>Ping оператора:</b>\n<code>{ping_host('10.0.0.2')}</code>", kb_vpn())

    # ── Logs ──
    elif data == "logs_menu":
        edit(chat_id, message_id, "📋 <b>Оберіть сервіс</b>", kb_logs())
    elif data.startswith("log_"):
        svc = data[4:]
        if svc == "actions":
            try:
                with open(ACTION_LOG) as f: lines = f.readlines()
                text_out = "".join(lines[-30:]) or "Порожньо"
            except Exception: text_out = "Немає файлу"
            edit(chat_id, message_id, f"<b>Журнал дій:</b>\n<pre>{text_out[-3500:]}</pre>", kb_back())
        else:
            edit(chat_id, message_id,
                 f"<b>Логи {svc}:</b>\n<pre>{get_logs(svc)[-3500:]}</pre>", kb_back())

    # ── Network ──
    elif data == "net_menu":
        edit(chat_id, message_id, "🌐 <b>Мережа</b>", kb_net())
    elif data == "ping_8888":
        edit(chat_id, message_id, "⏳...")
        edit(chat_id, message_id,
             f"📶 <b>Ping Google:</b>\n<code>{ping_host('8.8.8.8')}</code>", kb_net())
    elif data == "ping_operator":
        edit(chat_id, message_id, "⏳...")
        edit(chat_id, message_id,
             f"📶 <b>Ping оператора:</b>\n<code>{ping_host('10.0.0.2')}</code>", kb_net())
    elif data == "starlink_status":
        edit(chat_id, message_id, check_starlink(), kb_net())
    elif data == "screenshot":
        edit(chat_id, message_id, "📸 Беру кадр з запису...")
        # Знаходимо останній MP4 і витягуємо останній кадр через ffmpeg
        files = sorted(glob.glob(f"{RECORDINGS_DIR}/*.mp4"), reverse=True)
        snap_path = "/tmp/fpv_shot.jpg"
        ok = False
        if files:
            r = subprocess.run(
                ["ffmpeg", "-y", "-sseof", "-2", "-i", files[0],
                 "-frames:v", "1", "-q:v", "2", snap_path],
                capture_output=True, timeout=15)
            ok = r.returncode == 0 and os.path.exists(snap_path)
        if ok:
            with open(snap_path, "rb") as f:
                send_photo_bytes(f.read(), f"📹 Кадр з {os.path.basename(files[0])}")
            edit(chat_id, message_id, "📸 Надіслано", kb_net())
        else:
            edit(chat_id, message_id,
                 "❌ Немає записів або ffmpeg недоступний.\n"
                 "Переконайся що відео запис увімкнено (📹 Відео → 🔴 Запис)", kb_net())

    # ── Graphs ──
    elif data == "graphs_menu":
        edit(chat_id, message_id, "📈 <b>Графіки</b>", kb_graphs())
    elif data == "graph_temp":
        edit(chat_id, message_id, "⏳ Генерую графік...")
        img = make_graph(temp_history, "Температура CPU", "°C", "#e74c3c")
        if img:
            send_photo_bytes(img, f"🌡 CPU Temp — остання година")
            edit(chat_id, message_id, "📈 Графік надіслано", kb_graphs())
        else:
            edit(chat_id, message_id,
                 "⚠️ matplotlib не встановлено.\n<code>sudo apt install python3-matplotlib</code>",
                 kb_graphs())
    elif data == "graph_ping":
        edit(chat_id, message_id, "⏳ Генерую графік...")
        img = make_graph(ping_history, "Ping Google (8.8.8.8)", "ms", "#3498db")
        if img:
            send_photo_bytes(img, "📶 Ping — остання година")
            edit(chat_id, message_id, "📈 Графік надіслано", kb_graphs())
        else:
            edit(chat_id, message_id,
                 "⚠️ matplotlib не встановлено.\n<code>sudo apt install python3-matplotlib</code>",
                 kb_graphs())
    elif data == "graph_ping_text":
        edit(chat_id, message_id,
             f"<b>📊 Ping інтернету (8.8.8.8)</b>\n\n<pre>{ascii_ping_graph()}</pre>",
             kb_graphs())

    # ── Video ──
    elif data == "video_menu":
        edit(chat_id, message_id, "📹 <b>Відео</b>", kb_video())
    elif data == "rec_start":
        result = set_recording(True)
        edit(chat_id, message_id, result, kb_video())
    elif data == "rec_stop":
        result = set_recording(False)
        edit(chat_id, message_id, result, kb_video())
    elif data == "rec_list":
        edit(chat_id, message_id,
             f"<b>📁 Записи ({RECORDINGS_DIR}):</b>\n\n{list_recordings()}", kb_video())
    elif data == "rec_cleanup":
        cleanup_old_files(3)
        edit(chat_id, message_id, "🗑 Старі файли видалено", kb_video())

    # ── Config ──
    elif data == "config_menu":
        edit(chat_id, message_id, "⚙️ <b>Конфігурація</b>", kb_config())
    elif data == "cfg_view":
        content = read_env_file()
        edit(chat_id, message_id, f"<b>fpv.env:</b>\n<pre>{content}</pre>", kb_config())
    elif data == "cfg_edit":
        state[chat_id] = "wait_cfg"
        content = read_env_file()
        edit(chat_id, message_id,
             f"✏️ Надішли новий вміст fpv.env:\n\n<pre>{content}</pre>", kb_back())

    # ── Terminal ──
    elif data == "terminal":
        edit(chat_id, message_id, "🖥 <b>Термінал</b>", kb_terminal())
    elif data == "term_ls":
        edit(chat_id, message_id,
             f"<pre>{shell_exec('ls -la /home/pi/fpv/scripts/')}</pre>", kb_terminal())
    elif data == "term_df":
        edit(chat_id, message_id, f"<pre>{shell_exec('df -h /')}</pre>", kb_terminal())
    elif data == "term_temp":
        edit(chat_id, message_id,
             f"🌡 <code>{shell_exec('vcgencmd measure_temp 2>/dev/null || cat /sys/class/thermal/thermal_zone0/temp')}</code>",
             kb_terminal())
    elif data == "term_cpu":
        edit(chat_id, message_id, f"<pre>{shell_exec('top -bn1 | head -6')}</pre>", kb_terminal())
    elif data == "term_custom":
        state[chat_id] = "wait_cmd"
        edit(chat_id, message_id, "✏️ Введи shell команду:", kb_back())

    # ── Kill switch ──
    elif data == "killswitch_confirm":
        edit(chat_id, message_id,
             "🔴 <b>Kill Switch</b>\n\nВимкнути всі сервіси (vpn, video, rc)?",
             kb_confirm("killswitch_yes", "🔴 Вимкнути все"))
    elif data == "killswitch_yes":
        results = [run_service_cmd("stop", s) for s in SERVICES]
        alog("KILL SWITCH activated")
        edit(chat_id, message_id, "🔴 <b>Kill Switch активовано</b>\n\n" + "\n".join(results), kb_main())

    # ── Shutdown ──
    elif data == "shutdown_confirm":
        edit(chat_id, message_id,
             "⏹ <b>Безпечне вимкнення</b>\n\nПісля підтвердження Pi завершить всі процеси і повідомить коли можна вимикати живлення.",
             kb_confirm("shutdown_yes", "⏹ Вимкнути"))
    elif data == "shutdown_yes":
        edit(chat_id, message_id, "⏳ Зупиняю сервіси...")
        for s in SERVICES: run_service_cmd("stop", s)
        alog("SHUTDOWN initiated")
        send("⏹ <b>Pi вимикається...</b>\n\nЗачекайте <b>15 секунд</b> і вимикайте живлення. 🔌")
        threading.Thread(target=lambda: (time.sleep(3), subprocess.run(["sudo", "shutdown", "-h", "now"])),
                         daemon=True).start()

    # ── Reboot ──
    elif data == "reboot_confirm":
        edit(chat_id, message_id, "⚡ <b>Перезавантажити Pi?</b>",
             kb_confirm("reboot_yes", "⚡ Перезавантажити"))
    elif data == "reboot_yes":
        alog("REBOOT initiated")
        edit(chat_id, message_id, "🔄 Pi перезавантажується...")
        subprocess.Popen(["sudo", "reboot"])


# ══════════════════════════════════════════════════════════════════════════════
# Background monitors
# ══════════════════════════════════════════════════════════════════════════════

def ip_monitor():
    time.sleep(15)
    prev_local  = get_local_ip()
    prev_public = get_public_ip()

    send(
        f"🟢 <b>FPV Ground Station запущено</b>\n"
        f"🏠 Локальний IP: <code>{prev_local}</code>\n"
        f"🌐 Публічний IP: <code>{prev_public}</code>\n"
        f"📡 VPN Endpoint: <code>{get_wg_endpoint()}</code>\n"
        f"🌡 Температура:  <code>{get_cpu_temp():.1f}°C</code>\n\n"
        f"Надішли /start для меню керування."
    )

    last_cleanup = time.time()

    while True:
        time.sleep(CHECK_INTERVAL)

        # IP change
        new_local  = get_local_ip()
        new_public = get_public_ip()
        if new_local != prev_local or new_public != prev_public:
            send(
                f"🔄 <b>IP змінився!</b>\n"
                f"🏠 Локальний: <code>{new_local}</code> (було: <code>{prev_local}</code>)\n"
                f"🌐 Публічний: <code>{new_public}</code> (було: <code>{prev_public}</code>)\n"
                f"📡 VPN Endpoint: <code>{get_wg_endpoint()}</code>"
            )
            prev_local  = new_local
            prev_public = new_public

        # CPU overheat alert
        temp = get_cpu_temp()
        if temp > 80:
            send(f"🔥 <b>Перегрів CPU!</b> Температура: <code>{temp:.1f}°C</code>")

        # Disk alert
        disk_pct, disk_free = get_disk_usage()
        if disk_pct > 90:
            send(f"⚠️ <b>Диск майже заповнений!</b> {disk_pct}% (вільно {disk_free}GB)")

        # Auto cleanup every 24h
        if time.time() - last_cleanup > 86400:
            cleanup_old_files(3)
            last_cleanup = time.time()


def internet_monitor():
    time.sleep(30)
    was_online = True
    while True:
        time.sleep(30)
        ms = get_ping_ms("8.8.8.8")
        online = ms >= 0
        if online and not was_online:
            send("🌐 <b>Інтернет відновлено</b>")
        elif not online and was_online:
            send("❌ <b>Інтернет втрачено!</b>")
        was_online = online


# ══════════════════════════════════════════════════════════════════════════════
# Polling
# ══════════════════════════════════════════════════════════════════════════════

def poll():
    offset = 0
    log.info("Bot polling started")
    while True:
        try:
            r = tg_request("getUpdates", {
                "offset": offset, "timeout": 30,
                "allowed_updates": ["message", "callback_query"]
            })
            for update in r.get("result", []):
                offset = update["update_id"] + 1
                if "message" in update:
                    handle_message(update["message"])
                elif "callback_query" in update:
                    handle_callback(update["callback_query"])
        except Exception as e:
            log.error("Poll: %s", e); time.sleep(5)


def main():
    threading.Thread(target=ip_monitor,       daemon=True, name="ip-monitor").start()
    threading.Thread(target=internet_monitor, daemon=True, name="inet-monitor").start()
    threading.Thread(target=record_metrics,   daemon=True, name="metrics").start()
    poll()


if __name__ == "__main__":
    main()
