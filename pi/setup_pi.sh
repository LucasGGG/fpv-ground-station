#!/bin/bash
# FPV Ground Station - Raspberry Pi Setup Script
# Run as root: sudo bash setup_pi.sh

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

[[ $EUID -ne 0 ]] && error "Run as root: sudo bash $0"

INSTALL_DIR="/home/pi/fpv"
ENV_DIR="/etc/fpv"
SERVICE_DIR="/etc/systemd/system"

# ─── 1. System update ──────────────────────────────────────────────────────
info "Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq

# ─── 2. Install dependencies ───────────────────────────────────────────────
info "Installing dependencies..."
apt-get install -y -qq \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    python3 \
    python3-serial \
    wireguard \
    wireguard-tools \
    v4l-utils \
    usbutils

# ─── 3. Enable UART ────────────────────────────────────────────────────────
info "Configuring UART..."
CONFIG=/boot/firmware/config.txt
# Raspberry Pi 5 uses /boot/firmware/config.txt; Pi 4 uses /boot/config.txt
[[ ! -f $CONFIG ]] && CONFIG=/boot/config.txt

if ! grep -q "enable_uart=1" "$CONFIG"; then
    echo "" >> "$CONFIG"
    echo "# FPV - UART for CRSF" >> "$CONFIG"
    echo "enable_uart=1" >> "$CONFIG"
    echo "dtoverlay=disable-bt" >> "$CONFIG"
fi

# Disable serial console (conflicts with CRSF)
if grep -q "console=serial0" /boot/cmdline.txt 2>/dev/null; then
    sed -i 's/console=serial0,[0-9]* //' /boot/cmdline.txt
    warn "Removed serial console from cmdline.txt"
fi

# Add pi to dialout group for UART access
usermod -aG dialout pi

# ─── 4. Deploy scripts ─────────────────────────────────────────────────────
info "Deploying scripts to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR/scripts"
SCRIPT_SRC="$(dirname "$(realpath "$0")")/scripts"
rsync -a "$SCRIPT_SRC"/ "$INSTALL_DIR/scripts/"
chmod +x "$INSTALL_DIR/scripts/"*.sh
chown -R pi:pi "$INSTALL_DIR"

# ─── 5. Environment file ───────────────────────────────────────────────────
info "Creating environment file..."
mkdir -p "$ENV_DIR"
if [[ ! -f "$ENV_DIR/fpv.env" ]]; then
    cp "$(dirname "$(realpath "$0")")/config/fpv.env" "$ENV_DIR/fpv.env"
    chmod 640 "$ENV_DIR/fpv.env"
    warn "Edit $ENV_DIR/fpv.env with your OPERATOR_HOST IP"
fi

# ─── 6. WireGuard VPN ──────────────────────────────────────────────────────
info "Setting up WireGuard..."
mkdir -p /etc/wireguard
chmod 700 /etc/wireguard

if [[ ! -f /etc/wireguard/fpv0.conf ]]; then
    # Generate key pair
    PRIV=$(wg genkey)
    PUB=$(echo "$PRIV" | wg pubkey)
    echo "  Pi private key (keep secret): $PRIV"
    echo "  Pi public key (share with operator): $PUB"
    echo ""

    # Write stub config
    sed "s|<PI_PRIVATE_KEY>|$PRIV|" \
        "$(dirname "$(realpath "$0")")/config/fpv0.conf" \
        > /etc/wireguard/fpv0.conf
    chmod 600 /etc/wireguard/fpv0.conf

    warn "Fill in <OPERATOR_PUBLIC_KEY> and <OPERATOR_PUBLIC_IP> in /etc/wireguard/fpv0.conf"
else
    info "WireGuard config already exists, skipping."
fi

# ─── 7. Systemd services ───────────────────────────────────────────────────
info "Installing systemd services..."
SVC_SRC="$(dirname "$(realpath "$0")")/services"

for svc in vpn video_stream rc_control ip_notifier tg_bot watchdog web_dashboard; do
    [[ -f "$SVC_SRC/${svc}.service" ]] || continue
    cp "$SVC_SRC/${svc}.service" "$SERVICE_DIR/"
    systemctl daemon-reload
    systemctl enable "${svc}.service"
    info "Enabled: ${svc}.service"
done

# Timer для очищення записів
for timer in fpv_cleanup; do
    [[ -f "$SVC_SRC/${timer}.service" ]] && cp "$SVC_SRC/${timer}.service" "$SERVICE_DIR/"
    [[ -f "$SVC_SRC/${timer}.timer"   ]] && cp "$SVC_SRC/${timer}.timer"   "$SERVICE_DIR/"
done
systemctl daemon-reload
systemctl enable fpv_cleanup.timer 2>/dev/null && systemctl start fpv_cleanup.timer || true

# ─── 8. Kernel networking tweaks ───────────────────────────────────────────
info "Applying network performance tweaks..."
SYSCTL=/etc/sysctl.d/99-fpv.conf
cat > "$SYSCTL" << 'EOF'
# FPV low-latency UDP tuning
net.core.rmem_max=26214400
net.core.wmem_max=26214400
net.core.rmem_default=1048576
net.core.wmem_default=1048576
net.ipv4.udp_rmem_min=65536
net.ipv4.udp_wmem_min=65536
EOF
sysctl -p "$SYSCTL" > /dev/null

# ─── 9. Done ───────────────────────────────────────────────────────────────
echo ""
info "Setup complete. Next steps:"
echo "  1. Edit /etc/fpv/fpv.env — set OPERATOR_HOST"
echo "  2. Edit /etc/wireguard/fpv0.conf — set OPERATOR_PUBLIC_KEY and OPERATOR_PUBLIC_IP"
echo "  3. Configure operator PC WireGuard with Pi public key"
echo "  4. Reboot: sudo reboot"
echo "  5. After reboot, check: sudo systemctl status vpn video_stream rc_control"
echo ""
warn "A reboot is required for UART changes to take effect."
