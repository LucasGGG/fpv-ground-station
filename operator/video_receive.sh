#!/bin/bash
# Receive and display FPV video stream on operator PC
# Requires: ffplay (from ffmpeg) or GStreamer

PI_HOST="${PI_HOST:-10.0.0.1}"
VIDEO_PORT="${VIDEO_PORT:-5600}"

MODE="${1:-ffplay}"

case "$MODE" in
    ffplay)
        echo "Starting ffplay receiver from $PI_HOST:$VIDEO_PORT"
        ffplay -i "rtp://$PI_HOST:$VIDEO_PORT" \
               -fflags nobuffer \
               -flags low_delay \
               -framedrop \
               -strict experimental \
               -probesize 32 \
               -analyzeduration 0 \
               -sync ext \
               -vf "scale=720:480" \
               2>/dev/null
        ;;

    gst)
        echo "Starting GStreamer receiver from port $VIDEO_PORT"
        gst-launch-1.0 \
            udpsrc port=$VIDEO_PORT caps="application/x-rtp,media=video,encoding-name=H264,payload=96" \
            ! rtph264depay \
            ! h264parse \
            ! avdec_h264 \
            ! videoconvert \
            ! autovideosink sync=false
        ;;

    *)
        echo "Usage: $0 [ffplay|gst]"
        exit 1
        ;;
esac
