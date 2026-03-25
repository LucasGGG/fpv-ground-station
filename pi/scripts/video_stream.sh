#!/bin/bash
# FPV Video Streaming + Local Recording
# Пробує апаратний енкодер (v4l2h264enc), при невдачі — програмний x264

set -euo pipefail

DEVICE="${VIDEO_DEVICE:-/dev/video0}"
HOST="${OPERATOR_HOST:-10.0.0.2}"
PORT="${VIDEO_PORT:-5600}"
WIDTH="${VIDEO_WIDTH:-720}"
HEIGHT="${VIDEO_HEIGHT:-480}"
FPS="${VIDEO_FPS:-30}"
BITRATE="${VIDEO_BITRATE:-2000}"   # kbps
KEYFRAME="${VIDEO_KEYFRAME:-15}"   # кадрів між keyframe (0.5с @ 30fps)

RECORD_DIR="${RECORD_DIR:-/home/pi/fpv/recordings}"
RECORD="${ENABLE_RECORDING:-1}"

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

# Перевірка підтримки апаратного енкодера (вимкнено — нестабільний SPS/PPS)
has_hw_encoder() {
    return 1
}

run_pipeline_hw() {
    local outfile="$1"
    log "HW encoder: $DEVICE -> $HOST:$PORT | bitrate=${BITRATE}kbps | keyframe=${KEYFRAME}"

    local encode_branch="videoconvert ! v4l2h264enc \
        extra-controls=\"controls,repeat_sequence_header=1,video_bitrate=$((BITRATE * 1000)),h264_i_frame_period=${KEYFRAME}\" \
        ! video/x-h264,profile=baseline,level=(string)4.1 \
        ! h264parse config-interval=-1 disable-passthrough=true"

    if [ "$RECORD" = "1" ]; then
        exec gst-launch-1.0 -e \
            v4l2src device="$DEVICE" io-mode=mmap \
            ! video/x-raw,width=$WIDTH,height=$HEIGHT,framerate=$FPS/1 \
            ! $encode_branch \
            ! tee name=t \
            t. ! queue max-size-buffers=60 leaky=downstream \
               ! rtph264pay config-interval=-1 pt=96 \
               ! udpsink host="$HOST" port="$PORT" sync=false async=false \
            t. ! queue max-size-buffers=300 leaky=downstream \
               ! mp4mux faststart=true \
               ! filesink location="$outfile" sync=false
    else
        exec gst-launch-1.0 -e \
            v4l2src device="$DEVICE" io-mode=mmap \
            ! video/x-raw,width=$WIDTH,height=$HEIGHT,framerate=$FPS/1 \
            ! $encode_branch \
            ! rtph264pay config-interval=-1 pt=96 \
            ! udpsink host="$HOST" port="$PORT" sync=false async=false
    fi
}

run_pipeline_sw() {
    local outfile="$1"
    log "SW encoder (x264): $DEVICE -> $HOST:$PORT | bitrate=${BITRATE}kbps | keyframe=${KEYFRAME}"

    if [ "$RECORD" = "1" ]; then
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
                option-string="nal-hrd=cbr:annexb=1" \
            ! video/x-h264,profile=baseline \
            ! h264parse \
            ! tee name=t \
            t. ! queue max-size-buffers=60 leaky=downstream \
               ! rtph264pay config-interval=1 pt=96 \
               ! udpsink host="$HOST" port="$PORT" sync=false async=false \
            t. ! queue max-size-buffers=300 leaky=downstream \
               ! mp4mux faststart=true \
               ! filesink location="$outfile" sync=false
    else
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
            ! rtph264pay config-interval=1 pt=96 \
            ! udpsink host="$HOST" port="$PORT" sync=false async=false
    fi
}

main() {
    wait_for_device
    local use_hw=0
    has_hw_encoder && use_hw=1 && log "Апаратний H264 енкодер доступний" || log "Апаратний енкодер недоступний, використовую x264"

    while true; do
        mkdir -p "$RECORD_DIR"
        local ts outfile
        ts=$(date '+%Y%m%d_%H%M%S')
        outfile="$RECORD_DIR/fpv_${ts}.mp4"

        log "Запуск GStreamer pipeline..."
        if [ "$use_hw" = "1" ]; then
            run_pipeline_hw "$outfile" || { log "HW encoder failed, fallback to SW"; use_hw=0; }
        else
            run_pipeline_sw "$outfile" || true
        fi
        log "Pipeline зупинено, рестарт за 2с..."
        sleep 2
    done
}

main "$@"
