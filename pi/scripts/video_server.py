#!/usr/bin/env python3
"""
HTTP File Server для завантаження відео/фото записів.
Запускається на порту 8080, роздає файли з /home/pi/fpv/recordings/
"""

import http.server
import os
import datetime

RECORDINGS_DIR = "/home/pi/fpv/recordings"
PORT           = 8080


class RecordingsHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # вимикаємо stdout логи

    def do_GET(self):
        path = self.path.lstrip("/")

        # Головна сторінка — список файлів
        if path == "" or path == "index.html":
            self._list_files()
            return

        # Завантаження файлу
        file_path = os.path.join(RECORDINGS_DIR, os.path.basename(path))
        if os.path.exists(file_path) and os.path.isfile(file_path):
            self._serve_file(file_path)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"File not found")

    def _list_files(self):
        files = sorted(
            [f for f in os.listdir(RECORDINGS_DIR)
             if f.endswith((".mp4", ".jpg", ".jpeg"))],
            reverse=True
        )
        rows = ""
        for fname in files:
            fpath = os.path.join(RECORDINGS_DIR, fname)
            size  = os.path.getsize(fpath)
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath))
            size_str = f"{size // (1024*1024)} MB" if size > 1024*1024 else f"{size // 1024} KB"
            rows += (
                f'<tr>'
                f'<td><a href="/{fname}">{fname}</a></td>'
                f'<td>{size_str}</td>'
                f'<td>{mtime.strftime("%Y-%m-%d %H:%M")}</td>'
                f'<td><a href="/{fname}" download>⬇️ Завантажити</a></td>'
                f'</tr>\n'
            )

        html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>FPV Recordings</title>
<style>
  body {{ font-family: monospace; background: #111; color: #eee; padding: 20px; }}
  h1 {{ color: #e74c3c; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ padding: 8px 16px; border-bottom: 1px solid #333; text-align: left; }}
  a {{ color: #3498db; }}
  th {{ color: #aaa; }}
</style>
</head><body>
<h1>🚁 FPV Recordings</h1>
<p>{len(files)} файлів</p>
<table>
<tr><th>Файл</th><th>Розмір</th><th>Дата</th><th>Дія</th></tr>
{rows if rows else '<tr><td colspan="4">Немає записів</td></tr>'}
</table>
</body></html>"""

        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, file_path: str):
        fname = os.path.basename(file_path)
        ctype = "video/mp4" if fname.endswith(".mp4") else "image/jpeg"
        size  = os.path.getsize(file_path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
        self.end_headers()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)


if __name__ == "__main__":
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    server = http.server.HTTPServer(("0.0.0.0", PORT), RecordingsHandler)
    print(f"Video server running on port {PORT}")
    server.serve_forever()
