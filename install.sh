#!/usr/bin/env bash
# install.sh — deploy hello-operator on a Raspberry Pi
#
# Run from the project directory:
#   sudo ./install.sh
#
# Requires: Raspberry Pi OS (64-bit), internet access for apt and Piper download.

set -e

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
INSTALL_USER="$SUDO_USER"

echo "==> Installing hello-operator"
echo "    Project directory : $INSTALL_DIR"
echo "    Running as user   : $INSTALL_USER"
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
    alsa-utils \
    rtl-sdr \
    mpd \
    mpc \
    mopidy

# ---------------------------------------------------------------------------
# Config directory and files
# ---------------------------------------------------------------------------

echo "==> Creating config directory $CONFIG_DIR..."
mkdir -p "$CONFIG_DIR"
chmod 755 "$CONFIG_DIR"
chown "$INSTALL_USER:$INSTALL_USER" "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/config.env" ]; then
    echo "==> Copying config.env.example to $CONFIG_DIR/config.env..."
    cp "$INSTALL_DIR/config.env.example" "$CONFIG_DIR/config.env"
else
    echo "==> $CONFIG_DIR/config.env already exists — skipping (not overwritten)."
fi

if [ ! -f "$CONFIG_DIR/radio_stations.json" ]; then
    echo "==> Copying radio_stations.json.example to $CONFIG_DIR/radio_stations.json..."
    cp "$INSTALL_DIR/radio_stations.json.example" "$CONFIG_DIR/radio_stations.json"
else
    echo "==> $CONFIG_DIR/radio_stations.json already exists — skipping (not overwritten)."
fi

# ---------------------------------------------------------------------------
# Database directory
# ---------------------------------------------------------------------------

echo "==> Creating database directory /var/lib/hello-operator..."
mkdir -p /var/lib/hello-operator
chown "$INSTALL_USER:$INSTALL_USER" /var/lib/hello-operator
chmod 755 /var/lib/hello-operator

# ---------------------------------------------------------------------------
# TTS cache directory
# ---------------------------------------------------------------------------

echo "==> Creating TTS cache directory $CACHE_DIR..."
mkdir -p "$CACHE_DIR"
chown -R "$INSTALL_USER:$INSTALL_USER" "$(dirname "$CACHE_DIR")"

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
sudo -u "$INSTALL_USER" python3 -m venv "$INSTALL_DIR/venv"

echo "==> Installing Python dependencies..."
sudo -u "$INSTALL_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip wheel
sudo -u "$INSTALL_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements-pi.txt"
sudo -u "$INSTALL_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements-web.txt"

echo "==> Linking piper into $PIPER_BIN_DIR..."
ln -sf "$INSTALL_DIR/venv/bin/piper" "$PIPER_BIN_DIR/piper"
echo "==> Piper available at $PIPER_BIN_DIR/piper."

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

systemctl daemon-reload
systemctl enable hello-operator
systemctl enable hello-operator-web

echo "==> Configuring MPD music directory..."
MUSIC_DIR="/home/$INSTALL_USER/Music"
sed -i "s|^music_directory.*|music_directory \"$MUSIC_DIR\"|" /etc/mpd.conf

echo "==> Enabling and starting MPD..."
systemctl enable mpd
systemctl start mpd

# ---------------------------------------------------------------------------
# MAX98357 I2S amplifier
# ---------------------------------------------------------------------------

echo "==> Configuring MAX98357 I2S amplifier..."

# config.txt location varies by Raspberry Pi OS version (Bookworm vs Bullseye)
if [ -f /boot/firmware/config.txt ]; then
    CONFIG_TXT="/boot/firmware/config.txt"
elif [ -f /boot/config.txt ]; then
    CONFIG_TXT="/boot/config.txt"
else
    CONFIG_TXT=""
    echo "    WARNING: could not find config.txt — I2S overlay not configured."
fi

if [ -n "$CONFIG_TXT" ]; then
    if grep -q "dtoverlay=max98357a" "$CONFIG_TXT"; then
        echo "==> MAX98357 overlay already present in $CONFIG_TXT — skipping."
    else
        # Replace dtparam=audio=on with off, or append audio=off if absent
        if grep -q "^dtparam=audio=on" "$CONFIG_TXT"; then
            sed -i 's/^dtparam=audio=on/dtparam=audio=off/' "$CONFIG_TXT"
        elif ! grep -q "^dtparam=audio=off" "$CONFIG_TXT"; then
            echo "dtparam=audio=off" >> "$CONFIG_TXT"
        fi
        echo "dtoverlay=max98357a" >> "$CONFIG_TXT"
        echo "==> MAX98357 overlay added to $CONFIG_TXT."
    fi
fi

cat > /etc/asound.conf << 'ASOUND'
pcm.speakerbonnet {
    type hw
    card 0
}

pcm.dmixer {
    type dmix
    ipc_key 1024
    ipc_perm 0666
    slave {
        pcm "speakerbonnet"
        period_time 0
        period_size 1024
        buffer_size 8192
        rate 44100
        channels 2
    }
}

pcm.softvol {
    type softvol
    slave.pcm "dmixer"
    control.name "PCM"
    control.card 0
}

pcm.!default {
    type plug
    slave.pcm "softvol"
}
ASOUND
echo "==> /etc/asound.conf written."

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo ""
echo "==> Installation complete."
echo ""
echo "Next steps:"
echo "  1. Reboot so the MAX98357 I2S overlay takes effect:"
echo "       sudo reboot"
echo "     After rebooting, verify with: aplay -l"
echo "     Adjust volume with: alsamixer"
echo ""
echo "  2. Edit /etc/hello-operator/config.env and set:"
echo "       ASSISTANT_NUMBER   — required for all backends"
echo ""
echo "     If using MPD (default, MEDIA_BACKEND=mpd):"
echo "       MPD is already enabled and running. If the audio output device"
echo "       needs changing, edit /etc/mpd.conf and restart:"
echo "         sudo systemctl restart mpd"
echo "       MPD_HOST, MPD_PORT default to localhost:6600 — override if needed"
echo ""
echo "     If using Mopidy (MEDIA_BACKEND=mopidy):"
echo "       Configure Mopidy in /etc/mopidy/mopidy.conf and enable the"
echo "       mopidy-mpd extension, then:"
echo "         sudo systemctl enable mopidy && sudo systemctl start mopidy"
echo ""
echo "  3. (Optional) Edit /etc/hello-operator/radio_stations.json"
echo "     to add your local FM stations. Requires an RTL-SDR USB dongle."
echo ""
echo "  4. When ready, start the services:"
echo "       sudo systemctl start hello-operator"
echo "       sudo systemctl start hello-operator-web"
echo ""
echo "  5. Open the web interface in a browser on your local network:"
echo "       http://$(hostname).local:8080"
echo ""
echo "  See INSTALL.md for full configuration reference."
