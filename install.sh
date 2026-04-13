#!/usr/bin/env bash
# install.sh — deploy hello-operator on a Raspberry Pi
#
# Run from the project directory:
#   sudo ./install.sh
#
# Requires: Raspberry Pi OS (64-bit), internet access for apt and Piper download.

set -e

# ---------------------------------------------------------------------------
# Pinned Piper release — update these when a new version is available
# ---------------------------------------------------------------------------
PIPER_VERSION="2023.11.14-2"
PIPER_ARCH="aarch64"  # Raspberry Pi 4 (64-bit OS)
PIPER_TARBALL="piper_${PIPER_ARCH}.tar.gz"
PIPER_URL="https://github.com/OHF-Voice/piper1-gpl/releases/download/${PIPER_VERSION}/${PIPER_TARBALL}"

PIPER_MODEL_NAME="en_US-lessac-medium"
PIPER_MODEL_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/${PIPER_MODEL_NAME}.onnx"
PIPER_MODEL_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/${PIPER_MODEL_NAME}.onnx.json"

# ---------------------------------------------------------------------------
# Install paths
# ---------------------------------------------------------------------------
PIPER_BIN_DIR="/usr/local/bin"
PIPER_MODEL_DIR="/usr/local/share/piper"
CONFIG_DIR="/etc/hello-operator"
CACHE_DIR="/var/cache/hello-operator/tts"

# ---------------------------------------------------------------------------
# Check prerequisites
# ---------------------------------------------------------------------------

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run with sudo." >&2
    echo "Usage: sudo ./install.sh" >&2
    exit 1
fi

if [ -z "$SUDO_USER" ]; then
    echo "ERROR: SUDO_USER is not set. Run with sudo, not as root directly." >&2
    exit 1
fi

INSTALL_DIR="$(pwd)"
LOGIN_USER="$SUDO_USER"       # person who ran sudo (used for Angular build)
SERVICE_USER="hello-operator" # dedicated system account for both services

echo "==> Installing hello-operator"
echo "    Project directory : $INSTALL_DIR"
echo "    Login user        : $LOGIN_USER"
echo "    Service user      : $SERVICE_USER"
echo ""

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------

echo "==> Installing system packages..."
apt-get update -qq
apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    libportaudio2 \
    portaudio19-dev \
    alsa-utils \
    rtl-sdr

# ---------------------------------------------------------------------------
# Service user
# ---------------------------------------------------------------------------

echo "==> Creating service user '$SERVICE_USER'..."
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi
usermod -aG audio "$SERVICE_USER"
getent group gpio    && usermod -aG gpio    "$SERVICE_USER" || true
getent group plugdev && usermod -aG plugdev "$SERVICE_USER" || true

# ---------------------------------------------------------------------------
# Config directory and files
# ---------------------------------------------------------------------------

echo "==> Creating config directory $CONFIG_DIR..."
mkdir -p "$CONFIG_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_DIR"
chmod 750 "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/config.env" ]; then
    echo "==> Copying config.env.example to $CONFIG_DIR/config.env..."
    cp "$INSTALL_DIR/config.env.example" "$CONFIG_DIR/config.env"
else
    echo "==> $CONFIG_DIR/config.env already exists — skipping (not overwritten)."
fi
chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_DIR/config.env"
chmod 640 "$CONFIG_DIR/config.env"

if [ ! -f "$CONFIG_DIR/radio_stations.json" ]; then
    echo "==> Copying radio_stations.json.example to $CONFIG_DIR/radio_stations.json..."
    cp "$INSTALL_DIR/radio_stations.json.example" "$CONFIG_DIR/radio_stations.json"
else
    echo "==> $CONFIG_DIR/radio_stations.json already exists — skipping (not overwritten)."
fi
chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_DIR/radio_stations.json"
chmod 640 "$CONFIG_DIR/radio_stations.json"

# ---------------------------------------------------------------------------
# SQLite data directory
# ---------------------------------------------------------------------------

DB_DIR="/var/lib/hello-operator"
echo "==> Creating data directory $DB_DIR..."
mkdir -p "$DB_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$DB_DIR"
chmod 750 "$DB_DIR"

# ---------------------------------------------------------------------------
# TTS cache directory
# ---------------------------------------------------------------------------

echo "==> Creating TTS cache directory $CACHE_DIR..."
mkdir -p "$CACHE_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$(dirname "$CACHE_DIR")"

# ---------------------------------------------------------------------------
# Piper binary
# ---------------------------------------------------------------------------

if [ ! -f "$PIPER_BIN_DIR/piper" ]; then
    echo "==> Downloading Piper $PIPER_VERSION..."
    TMP_DIR="$(mktemp -d)"
    curl -fsSL "$PIPER_URL" -o "$TMP_DIR/$PIPER_TARBALL"
    tar -xzf "$TMP_DIR/$PIPER_TARBALL" -C "$TMP_DIR"
    install -m 755 "$TMP_DIR/piper/piper" "$PIPER_BIN_DIR/piper"
    rm -rf "$TMP_DIR"
    echo "==> Piper installed to $PIPER_BIN_DIR/piper."
else
    echo "==> Piper already installed at $PIPER_BIN_DIR/piper — skipping."
fi

# ---------------------------------------------------------------------------
# Piper voice model
# ---------------------------------------------------------------------------

mkdir -p "$PIPER_MODEL_DIR"

if [ ! -f "$PIPER_MODEL_DIR/${PIPER_MODEL_NAME}.onnx" ]; then
    echo "==> Downloading Piper voice model ${PIPER_MODEL_NAME}..."
    curl -fsSL "$PIPER_MODEL_URL"      -o "$PIPER_MODEL_DIR/${PIPER_MODEL_NAME}.onnx"
    curl -fsSL "$PIPER_MODEL_JSON_URL" -o "$PIPER_MODEL_DIR/${PIPER_MODEL_NAME}.onnx.json"
    echo "==> Voice model installed to $PIPER_MODEL_DIR."
else
    echo "==> Voice model already present at $PIPER_MODEL_DIR — skipping."
fi

# ---------------------------------------------------------------------------
# Python virtual environment
# ---------------------------------------------------------------------------

echo "==> Creating Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"

echo "==> Installing Python dependencies..."
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements-pi.txt"
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements-web.txt"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/venv"

# ---------------------------------------------------------------------------
# Angular frontend
# ---------------------------------------------------------------------------

if command -v npm >/dev/null 2>&1; then
    echo "==> Building Angular frontend..."
    (cd "$INSTALL_DIR/web/angular" && npm ci --quiet && npx ng build)
    echo "==> Angular frontend built."
else
    echo "==> Node.js/npm not found — skipping Angular build."
    echo "    The web UI will show a 'not built' page until you run:"
    echo "      cd $INSTALL_DIR/web/angular && npm install && npm run build"
fi

# ---------------------------------------------------------------------------
# Systemd service
# ---------------------------------------------------------------------------

echo "==> Generating systemd unit files..."
sed \
    -e "s|%%INSTALL_DIR%%|$INSTALL_DIR|g" \
    -e "s|%%USER%%|$SERVICE_USER|g" \
    "$INSTALL_DIR/hello-operator.service.template" \
    > /etc/systemd/system/hello-operator.service

sed \
    -e "s|%%INSTALL_DIR%%|$INSTALL_DIR|g" \
    -e "s|%%USER%%|$SERVICE_USER|g" \
    "$INSTALL_DIR/hello-operator-web.service.template" \
    > /etc/systemd/system/hello-operator-web.service

echo "==> Allowing web service to restart hello-operator without a password..."
echo "$SERVICE_USER ALL=(root) NOPASSWD: /bin/systemctl restart hello-operator" \
    > /etc/sudoers.d/hello-operator-web
chmod 440 /etc/sudoers.d/hello-operator-web

systemctl daemon-reload
systemctl enable hello-operator
systemctl enable hello-operator-web

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo ""
echo "==> Installation complete."
echo ""
echo "Next steps:"
echo "  1. Edit /etc/hello-operator/config.env and fill in:"
echo "       PLEX_TOKEN, PLEX_PLAYER_IDENTIFIER, ASSISTANT_NUMBER"
echo ""
echo "  2. (Optional) Edit /etc/hello-operator/radio_stations.json"
echo "     to add your local FM stations. Requires an RTL-SDR USB dongle."
echo ""
echo "  3. When ready, start the services:"
echo "       sudo systemctl start hello-operator"
echo "       sudo systemctl start hello-operator-web"
echo ""
echo "  4. Open the web interface in a browser on your local network:"
echo "       http://$(hostname).local:8080"
echo ""
echo "  See INSTALL.md for full configuration reference."
