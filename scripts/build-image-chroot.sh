#!/usr/bin/env bash
# build-image-chroot.sh — runs inside the ARM chroot during CI image build.
# NOT intended to be run directly on a Pi (use install.sh for that).
set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
INSTALL_DIR="/opt/hello-operator"
INSTALL_USER="hello-operator"

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
    alsa-utils \
    rtl-sdr \
    mpd \
    mpc \
    mopidy \
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
chmod 755 "$CONFIG_DIR"
chown "$INSTALL_USER:$INSTALL_USER" "$CONFIG_DIR"
cp "$INSTALL_DIR/config.env.example"          "$CONFIG_DIR/config.env"
cp "$INSTALL_DIR/radio_stations.json.example" "$CONFIG_DIR/radio_stations.json"
chown "$INSTALL_USER:$INSTALL_USER" "$CONFIG_DIR/config.env" "$CONFIG_DIR/radio_stations.json"

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
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip wheel
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements-pi.txt"
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements-web.txt"

echo "==> Linking piper into $PIPER_BIN_DIR..."
ln -sf "$INSTALL_DIR/venv/bin/piper" "$PIPER_BIN_DIR/piper"

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
ln -sf /lib/systemd/system/mpd.service \
        /etc/systemd/system/multi-user.target.wants/mpd.service

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
# Clean up to reduce image size
# ---------------------------------------------------------------------------
echo "==> Cleaning up..."
apt-get clean
rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo "==> Image setup complete. See INSTALL.md for post-flash configuration."
