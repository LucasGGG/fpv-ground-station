#!/bin/bash
# FPV Video Streaming + Local Recording
# GStreamer tee: одна гілка UDP RTP → оператор, друга → MP4 файл на Pi

set -euo pipefail

DEVICE="${VIDEO_DEVICE:-/dev/video0}"
HOST="${OPERATOR_HOST:-10.0.0.2}"
PORT="${VIDEO_PORT:-5600}"
WIDTH=720
HEIGHT=480
FPS=30
BITRATE=1200  # kbps

RECORD_DIR="${RECORD_DIR:-/home/pi/fpv/recordings}"
RECORD="${ENABLE_RECORDING:-1}"   # 1=увімкнено, 0=вимкнено

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

wait_for_device() {
    local retries=0
    while [ ! -e "$DEVICE" ]; do
        retries=$((retries + 1))
        if [ $retries -ge 30 ]; then
            log "ERROR: Device $DEVICE not found after 30s"
            exit 1
        fi
        log "Waiting for $DEVICE... ($retries)"
        sleep 1
    done
    log "Device $DEVICE ready"
}

run_pipeline() {
    local ts
    ts=$(date '+%Y%m%d_%H%M%S')
    local outfile="$RECORD_DIR/fpv_${ts}.mp4"
    mkdir -p "$RECORD_DIR"

    if [ "$RECORD" = "1" ]; then
        log "Starting stream+record: $DEVICE -> $HOST:$PORT | $outfile"
        exec gst-launch-1.0 -e \
            v4l2src device="$DEVICE" \
            ! video/x-raw,width=$WIDTH,height=$HEIGHT,framerate=$FPS/1 \
            ! videoconvert \
            ! x264enc \
                tune=zerolatency \
                speed-preset=ultrafast \
                bitrate=$BITRATE \
                key-int-max=$((FPS * 2)) \
                threads=2 \
            ! video/x-h264,profile=baseline \
            ! h264parse \
            ! tee name=t \
            t. ! queue max-size-buffers=300 leaky=downstream \
               ! rtph264pay config-interval=1 pt=96 \
               ! udpsink host="$HOST" port="$PORT" sync=false async=false \
            t. ! queue max-size-buffers=300 leaky=downstream \
               ! mp4mux faststart=true \
               ! filesink location="$outfile" sync=false
    else
        log "Starting stream only: $DEVICE -> $HOST:$PORT"
        exec gst-launch-1.0 -e \
            v4l2src device="$DEVICE" \
            ! video/x-raw,width=$WIDTH,height=$HEIGHT,framerate=$FPS/1 \
            ! videoconvert \
            ! x264enc \
                tune=zerolatency \
                speed-preset=ultrafast \
                bitrate=$BITRATE \
                key-int-max=$((FPS * 2)) \
                threads=2 \
            ! video/x-h264,profile=baseline \
            ! h264parse \
            ! rtph264pay config-interval=1 pt=96 \
            ! udpsink host="$HOST" port="$PORT" sync=false async=false
    fi
}

main() {
    wait_for_device
    while true; do
        log "Starting GStreamer pipeline..."
        if run_pipeline; then
            log "Pipeline exited cleanly"
        else
            log "Pipeline crashed (exit $?), restarting in 2s..."
        fi
        sleep 2
    done
}

main "$@"
