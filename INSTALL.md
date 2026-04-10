# Installation Guide

## Prerequisites

- Raspberry Pi 4
- Plex Media Server running and accessible on the network
- Hardware wired up per the setup guides in `docs/`:
  - `docs/AMP_SETUP.md` — MAX98357 I2S amplifier
  - `docs/BREAKBEAM_SETUP.md` — IR breakbeam pulse switch
  - `docs/HOOK_SWITCH_SETUP.md` — hook switch

There are two installation paths. Both end up at the same [Configure](#step-configure) step.

---

## Option A — Flash a pre-built image

The GitHub Actions build workflow produces a ready-to-flash Raspberry Pi OS image with everything pre-installed. This is the fastest way to get started.

### Step A1 — Download the image

Go to the [Releases](../../releases) page and download the latest `hello-operator-*.img.xz`.

Alternatively, download the most recent build artifact from the [Actions](../../actions/workflows/build-image.yml) tab (requires a GitHub account).

### Step A2 — Flash with Raspberry Pi Imager

1. Open [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Under **Device**, choose Raspberry Pi 4.
3. Under **OS**, choose **Use custom** and select the downloaded `.img.xz` file.
4. Under **Storage**, choose your microSD card.
5. Click **Next**. When asked about OS customisation, configure your username, password, and Wi-Fi credentials.
6. Flash and eject the card.

### Step A3 — Boot and configure

Insert the card, boot the Pi, and SSH in. Then continue at [Configure](#step-configure) below.

---

## Option B — Clone and install on a running Pi

Use this path if you already have Raspberry Pi OS running and want to install hello-operator on top of it.

### Step B1 — Clone the repository

```bash
git clone <repo-url> hello-operator
cd hello-operator
```

### Step B2 — Run the install script

```bash
sudo ./install.sh
```

The script installs system packages, downloads and installs the Piper TTS binary and voice model, creates a Python virtual environment, installs pip dependencies, creates `/etc/hello-operator/` with example config files, generates and installs the systemd unit file, and enables the service for auto-start on boot.

---

## Step — Configure

Edit `/etc/hello-operator/config.env`. The file is pre-populated from `config.env.example` with comments explaining each variable.

### Required

| Variable | Description |
|---|---|
| `PLEX_TOKEN` | Your Plex authentication token |
| `PLEX_PLAYER_IDENTIFIER` | Machine identifier of the Plex player to control |
| `ASSISTANT_NUMBER` | 7-digit reserved number for the diagnostic assistant (must not conflict with any media entry) |

**Finding your `PLEX_TOKEN`:** Sign in to Plex Web, open `https://plex.tv/devices.xml` in the same browser session, and copy the token from the URL or the XML. Full instructions: https://support.plex.tv/articles/204059436

**Finding your `PLEX_PLAYER_IDENTIFIER`:** In Plex Web → Settings → Troubleshooting, copy the Machine Identifier shown at the top of the page.

### Optional

These have sensible defaults matching the install script's paths and the hardware wiring guides. Override if your setup differs.

> **Note for pre-built image users:** `PIPER_BINARY`, `PIPER_MODEL`, `TTS_CACHE_DIR`, `HOOK_SWITCH_PIN`, and `PULSE_SWITCH_PIN` are already correct for the baked image and do not need to be changed unless your hardware differs.

| Variable | Default | Description |
|---|---|---|
| `PLEX_URL` | `http://localhost:32400` | Plex server URL |
| `HOOK_SWITCH_PIN` | `17` | BCM GPIO pin for hook switch |
| `PULSE_SWITCH_PIN` | `27` | BCM GPIO pin for pulse switch |
| `PIPER_BINARY` | `/usr/local/bin/piper` | Path to Piper binary |
| `PIPER_MODEL` | `/usr/local/share/piper/en_US-lessac-medium.onnx` | Path to Piper voice model |
| `TTS_CACHE_DIR` | `/var/cache/hello-operator/tts` | Directory for pre-rendered TTS audio files |

---

## Step — Configure radio stations (optional)

Edit `/etc/hello-operator/radio_stations.json`. The file is pre-populated with example entries from `radio_stations.json.example`. Replace or extend with your local stations:

```json
[
  { "name": "KEXP",  "frequency_mhz": 90.3, "phone_number": "5550903" },
  { "name": "KNKX",  "frequency_mhz": 88.5, "phone_number": "5550885" }
]
```

| Field | Description |
|---|---|
| `name` | Station name, spoken aloud when connecting |
| `frequency_mhz` | FM carrier frequency in MHz (e.g. `90.3`) |
| `phone_number` | 7-digit direct-dial number; must not match `ASSISTANT_NUMBER` |

Convention: use `555` as the prefix followed by four digits representing the frequency — e.g. `5550903` for 90.3 MHz.

To disable radio entirely without removing the file, use an empty array: `[]`

An RTL-SDR USB dongle (RTL2832U) must be plugged in for radio playback to work.

---

## Step — Start

```bash
sudo systemctl start hello-operator
sudo systemctl status hello-operator
```

Pick up the handset. You should hear a dial tone followed by the operator greeting.

---

## Viewing logs

```bash
sudo journalctl -u hello-operator -f
```

---

## Stopping and restarting

```bash
sudo systemctl stop hello-operator
sudo systemctl restart hello-operator
```

---

## Troubleshooting

| Symptom | Where to look |
|---|---|
| No audio from handset | `docs/AMP_SETUP.md` |
| Dial pulses not detected | `docs/BREAKBEAM_SETUP.md` |
| Handset lift not detected | `docs/HOOK_SWITCH_SETUP.md` |
| Service fails to start | `sudo journalctl -u hello-operator -n 50` |
| Error about `PLEX_TOKEN` at startup | Check `/etc/hello-operator/config.env` — the variable must be set |
| Error about `ASSISTANT_NUMBER` at startup | Set `ASSISTANT_NUMBER` in `/etc/hello-operator/config.env` |
| Radio plays no audio | Confirm RTL-SDR dongle is plugged in; run `rtl_test` to verify it is detected |
