#!/bin/bash
# FPV Video Streaming - GStreamer pipeline
# Captures from USB capture card, encodes H264, streams via UDP RTP

set -euo pipefail

DEVICE="${VIDEO_DEVICE:-/dev/video0}"
HOST="${OPERATOR_HOST:-10.0.0.2}"
PORT="${VIDEO_PORT:-5600}"
WIDTH=720
HEIGHT=480
FPS=30
BITRATE=1200  # kbps

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
    log "Starting stream: $DEVICE -> $HOST:$PORT @ ${WIDTH}x${HEIGHT}@${FPS}fps ${BITRATE}kbps"
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
