#!/bin/bash
SDP="${1:-/Users/canotti/Documents/RP4+Starlink/operator/fpv.sdp}"

echo "▶ FPV Stream"
ffplay \
    -protocol_whitelist file,udp,rtp \
    -i "$SDP" \
    -fflags nobuffer \
    -flags low_delay \
    -framedrop \
    -window_title "FPV Ground Station" \
    2>/dev/null
