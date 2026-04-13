#!/usr/bin/env bash
# build-image-chroot.sh — runs inside the ARM chroot during CI image build.
# NOT intended to be run directly on a Pi (use install.sh for that).
set -euo pipefail

# ---------------------------------------------------------------------------
# Paths and versions — keep PIPER_VERSION in sync with install.sh
# ---------------------------------------------------------------------------
INSTALL_DIR="/opt/hello-operator"
INSTALL_USER="hello-operator"

PIPER_VERSION="2023.11.14-2"
PIPER_ARCH="aarch64"
PIPER_TARBALL="piper_${PIPER_ARCH}.tar.gz"
PIPER_URL="https://github.com/OHF-Voice/piper1-gpl/releases/download/${PIPER_VERSION}/${PIPER_TARBALL}"
PIPER_MODEL_NAME="en_US-lessac-medium"
PIPER_MODEL_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

PIPER_BIN_DIR="/usr/local/bin"
PIPER_MODEL_DIR="/usr/local/share/piper"
CONFIG_DIR="/etc/hello-operator"
CACHE_DIR="/var/cache/hello-operator/tts"

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------
echo "==> Installing system packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    libportaudio2 \
    portaudio19-dev \
    alsa-utils \
    rtl-sdr \
    curl

# ---------------------------------------------------------------------------
# Service user
# ---------------------------------------------------------------------------
echo "==> Creating service user '$INSTALL_USER'..."
useradd --system --no-create-home --shell /usr/sbin/nologin "$INSTALL_USER"
usermod -aG audio "$INSTALL_USER"
getent group gpio    && usermod -aG gpio    "$INSTALL_USER"
getent group plugdev && usermod -aG plugdev "$INSTALL_USER"

# ---------------------------------------------------------------------------
# Config directory and files
# ---------------------------------------------------------------------------
echo "==> Setting up config directory $CONFIG_DIR..."
mkdir -p "$CONFIG_DIR"
chown "$INSTALL_USER:$INSTALL_USER" "$CONFIG_DIR"
chmod 750 "$CONFIG_DIR"
cp "$INSTALL_DIR/config.env.example"          "$CONFIG_DIR/config.env"
cp "$INSTALL_DIR/radio_stations.json.example" "$CONFIG_DIR/radio_stations.json"
chown "$INSTALL_USER:$INSTALL_USER" "$CONFIG_DIR/config.env" "$CONFIG_DIR/radio_stations.json"
chmod 640 "$CONFIG_DIR/config.env" "$CONFIG_DIR/radio_stations.json"

# ---------------------------------------------------------------------------
# SQLite data directory
# ---------------------------------------------------------------------------
DB_DIR="/var/lib/hello-operator"
echo "==> Creating data directory $DB_DIR..."
mkdir -p "$DB_DIR"
chown "$INSTALL_USER:$INSTALL_USER" "$DB_DIR"
chmod 750 "$DB_DIR"

# ---------------------------------------------------------------------------
# TTS cache directory
# ---------------------------------------------------------------------------
echo "==> Creating TTS cache directory $CACHE_DIR..."
mkdir -p "$CACHE_DIR"
chown -R "$INSTALL_USER:$INSTALL_USER" "$(dirname "$CACHE_DIR")"

# ---------------------------------------------------------------------------
# Piper binary
# ---------------------------------------------------------------------------
echo "==> Downloading Piper $PIPER_VERSION..."
TMP_DIR="$(mktemp -d)"
curl -fsSL "$PIPER_URL" -o "$TMP_DIR/$PIPER_TARBALL"
tar -xzf "$TMP_DIR/$PIPER_TARBALL" -C "$TMP_DIR"
install -m 755 "$TMP_DIR/piper/piper" "$PIPER_BIN_DIR/piper"
rm -rf "$TMP_DIR"

# ---------------------------------------------------------------------------
# Piper voice model
# ---------------------------------------------------------------------------
echo "==> Downloading Piper voice model $PIPER_MODEL_NAME..."
mkdir -p "$PIPER_MODEL_DIR"
curl -fsSL "${PIPER_MODEL_BASE}/${PIPER_MODEL_NAME}.onnx"      -o "$PIPER_MODEL_DIR/${PIPER_MODEL_NAME}.onnx"
curl -fsSL "${PIPER_MODEL_BASE}/${PIPER_MODEL_NAME}.onnx.json" -o "$PIPER_MODEL_DIR/${PIPER_MODEL_NAME}.onnx.json"

# ---------------------------------------------------------------------------
# Python virtual environment and dependencies
# ---------------------------------------------------------------------------
echo "==> Creating Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"

echo "==> Installing Python dependencies..."
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements-pi.txt"
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements-web.txt"

# ---------------------------------------------------------------------------
# Ownership and systemd service
# ---------------------------------------------------------------------------
echo "==> Setting ownership of $INSTALL_DIR..."
chown -R "$INSTALL_USER:$INSTALL_USER" "$INSTALL_DIR"

echo "==> Installing systemd services..."
sed \
    -e "s|%%INSTALL_DIR%%|$INSTALL_DIR|g" \
    -e "s|%%USER%%|$INSTALL_USER|g" \
    "$INSTALL_DIR/hello-operator.service.template" \
    > /etc/systemd/system/hello-operator.service

sed \
    -e "s|%%INSTALL_DIR%%|$INSTALL_DIR|g" \
    -e "s|%%USER%%|$INSTALL_USER|g" \
    "$INSTALL_DIR/hello-operator-web.service.template" \
    > /etc/systemd/system/hello-operator-web.service

echo "==> Allowing web service to restart hello-operator without a password..."
echo "$INSTALL_USER ALL=(root) NOPASSWD: /bin/systemctl restart hello-operator" \
    > /etc/sudoers.d/hello-operator-web
chmod 440 /etc/sudoers.d/hello-operator-web

# Enable at boot (systemctl not available in a chroot — create symlinks directly).
mkdir -p /etc/systemd/system/multi-user.target.wants
ln -sf /etc/systemd/system/hello-operator.service \
        /etc/systemd/system/multi-user.target.wants/hello-operator.service
ln -sf /etc/systemd/system/hello-operator-web.service \
        /etc/systemd/system/multi-user.target.wants/hello-operator-web.service

# ---------------------------------------------------------------------------
# Clean up to reduce image size
# ---------------------------------------------------------------------------
echo "==> Cleaning up..."
apt-get clean
rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "==> Image setup complete."
echo ""
echo "After flashing, boot the Pi and complete setup:"
echo "  1. Edit /etc/hello-operator/config.env"
echo "     Set PLEX_TOKEN, PLEX_PLAYER_IDENTIFIER, and ASSISTANT_NUMBER"
echo "  2. (Optional) Edit /etc/hello-operator/radio_stations.json"
echo "  3. sudo systemctl start hello-operator"
echo "  4. sudo journalctl -u hello-operator -f"
