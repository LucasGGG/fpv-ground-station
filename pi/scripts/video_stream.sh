#!/bin/bash
# FPV Video Streaming — stream only, no recording

set -euo pipefail

DEVICE="${VIDEO_DEVICE:-/dev/video0}"
HOST="${OPERATOR_HOST:-10.0.0.2}"
PORT="${VIDEO_PORT:-5600}"
WIDTH="${VIDEO_WIDTH:-720}"
HEIGHT="${VIDEO_HEIGHT:-480}"
FPS="${VIDEO_FPS:-30}"
BITRATE="${VIDEO_BITRATE:-2000}"
KEYFRAME="${VIDEO_KEYFRAME:-15}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

wait_for_device() {
    local retries=0
    while [ ! -e "$DEVICE" ]; do
        retries=$((retries + 1))
        [ $retries -ge 30 ] && { log "ERROR: $DEVICE не знайдено"; exit 1; }
        log "Waiting for $DEVICE... ($retries)"
        sleep 1
    done
    log "Device $DEVICE ready"
}

run_pipeline() {
    log "Starting stream: $DEVICE -> $HOST:$PORT | ${WIDTH}x${HEIGHT}@${FPS}fps | ${BITRATE}kbps"
    exec gst-launch-1.0 -e \
        v4l2src device="$DEVICE" \
        ! video/x-raw,width=$WIDTH,height=$HEIGHT,framerate=$FPS/1 \
        ! videoconvert \
        ! x264enc \
            tune=zerolatency \
            speed-preset=superfast \
            bitrate=$BITRATE \
            key-int-max=$KEYFRAME \
            threads=2 \
            sliced-threads=true \
        ! video/x-h264,profile=baseline \
        ! h264parse \
        ! rtph264pay config-interval=-1 pt=96 \
        ! udpsink host="$HOST" port="$PORT" sync=false async=false
}

main() {
    wait_for_device
    while true; do
        run_pipeline || true
        log "Pipeline зупинено, рестарт за 2с..."
        sleep 2
    done
}

main "$@"
