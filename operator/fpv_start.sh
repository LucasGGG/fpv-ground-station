#!/bin/bash
# fpv-start — запускає VPN, відео та RC управління одною командою

WG_CONF="/Users/canotti/Documents/RP4+Starlink/operator/fpv0_operator.conf"
SDP="/Users/canotti/Documents/RP4+Starlink/operator/fpv.sdp"
RC_SENDER="/Users/canotti/Documents/RP4+Starlink/operator/rc_sender.py"
PI_HOST="10.0.0.1"

log() { echo "[fpv-start] $*"; }

# ── 1. VPN ──────────────────────────────────────────────────────────────────
log "Піднімаю WireGuard..."
if ping -c 1 -W 1000 "$PI_HOST" &>/dev/null; then
    log "VPN вже активний"
else
    sudo /opt/homebrew/bin/bash /opt/homebrew/bin/wg-quick up "$WG_CONF" 2>/dev/null || true
    log "Чекаю тунель..."
    for i in $(seq 1 15); do
        ping -c 1 -W 1000 "$PI_HOST" &>/dev/null && break
        sleep 1
        if [ $i -eq 15 ]; then
            log "❌ VPN не підключився. Перевір WireGuard."
            exit 1
        fi
    done
    log "VPN підключено (${PI_HOST})"
fi

# ── 2. Відео (фоновий процес) ────────────────────────────────────────────────
log "Запускаю відео..."
ffplay \
    -protocol_whitelist file,udp,rtp \
    -i "$SDP" \
    -fflags nobuffer \
    -flags low_delay \
    -framedrop \
    -window_title "FPV Ground Station" \
    2>/dev/null &
VIDEO_PID=$!
log "ffplay PID=$VIDEO_PID"

# ── 3. RC управління (foreground) ───────────────────────────────────────────
log "Запускаю RC управління (Ctrl+C для виходу)..."
sleep 1
PI_HOST="$PI_HOST" python3 "$RC_SENDER"

# ── Cleanup ──────────────────────────────────────────────────────────────────
log "Зупиняю відео..."
kill $VIDEO_PID 2>/dev/null || true
log "Готово."
