#!/usr/bin/env python3
"""
FPV Web Dashboard — проста сторінка зі статусом сервісів та логами
Порт: 8080 (http://pi.local:8080 або http://10.0.0.1:8080)
"""

import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

PORT = int(os.environ.get("WEB_PORT", "8080"))

SERVICES = ["video_stream", "rc_control", "vpn", "tg_bot", "ip_notifier", "watchdog"]


def run(cmd, timeout=5) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return str(e)


def service_status(name: str) -> dict:
    active = run(f"systemctl is-active {name}")
    uptime = run(f"systemctl show {name} --property=ActiveEnterTimestamp --value")
    return {"name": name, "active": active == "active", "status": active, "since": uptime}


def get_logs(name: str, lines=30) -> str:
    return run(f"journalctl -u {name} --no-pager -n {lines} --output=short")


def get_system_info() -> dict:
    cpu    = run("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")
    mem    = run("free -m | awk 'NR==2{printf \"%s/%s MB\", $3,$2}'")
    temp   = run("vcgencmd measure_temp 2>/dev/null | cut -d= -f2")
    disk   = run("df -h / | awk 'NR==2{print $3\"/\"$2\" (\"$5\")\"}'")
    uptime = run("uptime -p")
    return {"cpu": cpu, "mem": mem, "temp": temp, "disk": disk, "uptime": uptime}


def render_html(service_log: str = "", log_service: str = "") -> str:
    statuses = [service_status(s) for s in SERVICES]
    info = get_system_info()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = ""
    for s in statuses:
        color = "#2ecc71" if s["active"] else "#e74c3c"
        icon  = "●" if s["active"] else "○"
        rows += f"""
        <tr>
          <td><span style="color:{color}">{icon}</span> {s['name']}</td>
          <td style="color:{color}">{s['status']}</td>
          <td style="font-size:0.8em;color:#aaa">{s['since'][:19] if s['since'] else '—'}</td>
          <td>
            <a href="/logs?service={s['name']}" class="btn">Логи</a>
            <a href="/restart?service={s['name']}" class="btn btn-warn"
               onclick="return confirm('Рестартувати {s[\"name\"]}?')">Restart</a>
          </td>
        </tr>"""

    log_section = ""
    if service_log:
        log_section = f"""
        <div class="card">
          <h2>📋 Логи: {log_service}</h2>
          <pre class="logs">{service_log}</pre>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="15">
  <title>FPV Ground Station</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #1a1a2e; color: #eee; font-family: monospace; padding: 20px; }}
    h1 {{ color: #00d4ff; margin-bottom: 20px; }}
    h2 {{ color: #00d4ff; margin-bottom: 10px; font-size: 1em; }}
    .card {{ background: #16213e; border-radius: 8px; padding: 15px; margin-bottom: 15px; }}
    .info-grid {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(150px,1fr)); gap: 10px; }}
    .info-item {{ background: #0f3460; border-radius: 6px; padding: 10px; text-align: center; }}
    .info-item .val {{ font-size: 1.2em; color: #00d4ff; }}
    .info-item .lbl {{ font-size: 0.75em; color: #aaa; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td {{ padding: 8px 10px; border-bottom: 1px solid #0f3460; }}
    .btn {{ background: #0f3460; color: #eee; border: none; padding: 4px 10px;
            border-radius: 4px; cursor: pointer; text-decoration: none; font-size: 0.8em; margin-right: 4px; }}
    .btn-warn {{ background: #7f1d1d; }}
    .logs {{ background: #0a0a1a; padding: 10px; border-radius: 4px; overflow-x: auto;
             white-space: pre-wrap; font-size: 0.75em; max-height: 400px; overflow-y: auto; }}
    .footer {{ color: #555; font-size: 0.75em; margin-top: 20px; text-align: center; }}
  </style>
</head>
<body>
  <h1>🚁 FPV Ground Station</h1>

  <div class="card">
    <h2>🖥 Система</h2>
    <div class="info-grid">
      <div class="info-item"><div class="val">{info['temp']}</div><div class="lbl">Температура</div></div>
      <div class="info-item"><div class="val">{info['cpu']}%</div><div class="lbl">CPU</div></div>
      <div class="info-item"><div class="val">{info['mem']}</div><div class="lbl">RAM</div></div>
      <div class="info-item"><div class="val">{info['disk']}</div><div class="lbl">Диск</div></div>
      <div class="info-item"><div class="val" style="font-size:0.9em">{info['uptime']}</div><div class="lbl">Uptime</div></div>
    </div>
  </div>

  <div class="card">
    <h2>⚙️ Сервіси</h2>
    <table>{rows}</table>
  </div>

  {log_section}

  <div class="footer">Оновлено: {now} | auto-refresh 15s</div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_html(self, html: str, code=200):
        body = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/":
            self.send_html(render_html())

        elif parsed.path == "/logs":
            svc = params.get("service", ["video_stream"])[0]
            if svc in SERVICES:
                logs = get_logs(svc, 50)
                self.send_html(render_html(logs, svc))
            else:
                self.send_html(render_html())

        elif parsed.path == "/restart":
            svc = params.get("service", [""])[0]
            if svc in SERVICES:
                run(f"systemctl restart {svc}")
                time.sleep(1)
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()

        else:
            self.send_html("<h1>404</h1>", 404)


def main():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[web_dashboard] http://0.0.0.0:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
