# Installation Guide

## Prerequisites

- Raspberry Pi 4
- A supported media player: **MPD (Music Player Daemon)** or **Mopidy** running and accessible on the network
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

The script installs system packages, downloads the Piper TTS binary and voice model, creates a Python virtual environment, installs pip dependencies, creates `/etc/hello-operator/` with example config files, and generates and enables both systemd unit files.

If Node.js (`npm`) is available on the machine, `install.sh` also builds the Angular frontend so the web interface is fully operational at `http://<hostname>.local:8080` immediately after starting the service. If Node.js is not present, the API works but the browser UI shows a "not built" message; build it manually:

```bash
cd web/angular && npm install && npm run build
```

---

## Step — Configure

Edit `/etc/hello-operator/config.env`. The file is pre-populated from `config.env.example` with comments explaining each variable.

### MPD and Mopidy backends

Set `MEDIA_BACKEND=mpd` to connect to a Music Player Daemon instance, or `MEDIA_BACKEND=mopidy` to connect to a Mopidy server. Both use the same `MPD_HOST` and `MPD_PORT` variables — Mopidy implements the MPD wire protocol via its `mopidy-mpd` extension.

**MPD setup notes:**
- MPD is installed and enabled automatically by the install script and pre-built image.
- The install script configures MPD to look for music in `~/Music`. Image users need to set this manually in `/etc/mpd.conf`:
  ```
  music_directory "/home/<your-username>/Music"
  ```
- After adding files to your Music folder, update the MPD database so they appear in the library:
  ```bash
  mpc update
  ```
- If the audio output device needs changing from the system default, edit `/etc/mpd.conf` and restart: `sudo systemctl restart mpd`

**Mopidy setup notes:**
- Install the MPD frontend extension: `sudo pip install mopidy-mpd`
- In `/etc/mopidy/mopidy.conf`, enable the MPD extension and set `hostname = ::` (or `0.0.0.0`) so hello-operator can reach it over the network
- Mopidy's MPD frontend defaults to port 6600, matching the `MPD_PORT` default

### Optional

These have sensible defaults matching the install script's paths and the hardware wiring guides. Override if your setup differs.

> **Note for pre-built image users:** `PIPER_BINARY`, `PIPER_MODEL`, `TTS_CACHE_DIR`, `HOOK_SWITCH_PIN`, and `PULSE_SWITCH_PIN` are already correct for the baked image and do not need to be changed unless your hardware differs.

| Variable | Default | Description |
|---|---|---|
| `ASSISTANT_NUMBER` | '5550000' | 7-digit reserved number for the diagnostic assistant |
| `MEDIA_BACKEND` | `mpd` | Media player backend: `mpd` or `mopidy` |
| `MPD_HOST` | `localhost` | MPD/Mopidy server hostname or IP |
| `MPD_PORT` | `6600` | MPD/Mopidy TCP port (MPD and Mopidy backends) |
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
sudo systemctl start hello-operator-web
```

Open a browser on any device on the same Wi-Fi network and navigate to:

```
http://<pi-hostname>.local:8080
```

The default hostname on Raspberry Pi OS is `raspberrypi`, so the address is typically `http://raspberrypi.local:8080`. The web interface shows system status, project documentation, and the full configuration editor.

Pick up the handset to confirm the phone system is working. You should hear a dial tone followed by the operator greeting.

---

## Web interface

After both services are running, the web interface is available at `http://<hostname>.local:8080` from any device on the same network. It is a single-page Angular application backed by a Flask REST API.

Three views are available via the top navigation bar:

| View | Path | Purpose |
|---|---|---|
| **Status** | `/` | Service state badge and one-click restart |
| **Docs** | `/docs` | Browsable project documentation rendered from Markdown |
| **Configure** | `/config` | Edit all settings and radio stations without touching the command line |

Configuration changes written through the UI are saved to `/etc/hello-operator/config.env` and `/etc/hello-operator/radio_stations.json`. The phone service is restarted automatically after each save.

**REST API** — the backend exposes the following JSON endpoints (useful for scripting or diagnostics):

| Endpoint | Method | Description |
|---|---|---|
| `/api/status` | GET | Current systemd active state |
| `/service/restart` | POST | Restart hello-operator |
| `/api/docs` | GET | List of available documentation pages |
| `/api/docs/<slug>` | GET | Raw Markdown content for a single page |
| `/api/config` | GET | Config field definitions, current values, and radio stations |
| `/api/config/env` | POST | Save environment variable updates (JSON body) |
| `/api/config/radio` | POST | Save radio station list (JSON body) |

---

## Viewing logs

```bash
# Phone system
sudo journalctl -u hello-operator -f

# Web interface
sudo journalctl -u hello-operator-web -f
```

---

## Stopping and restarting

```bash
sudo systemctl stop hello-operator
sudo systemctl restart hello-operator

sudo systemctl stop hello-operator-web
sudo systemctl restart hello-operator-web
```

---

## Troubleshooting

| Symptom | Where to look |
|---|---|
| No audio from handset | `docs/AMP_SETUP.md` |
| Dial pulses not detected | `docs/BREAKBEAM_SETUP.md` |
| Handset lift not detected | `docs/HOOK_SWITCH_SETUP.md` |
| Service fails to start | `sudo journalctl -u hello-operator -n 50` |
| Web interface unreachable | Check `sudo systemctl status hello-operator-web`; confirm port 8080 is not blocked |
| Radio plays no audio | Confirm RTL-SDR dongle is plugged in; run `rtl_test` to verify it is detected |
| MPD connection refused | Confirm MPD is running (`systemctl status mpd`) and `MPD_HOST`/`MPD_PORT` match |
| Mopidy connection refused | Confirm Mopidy is running (`systemctl status mopidy`) and the MPD extension is enabled (`mopidy-mpd`); check `MPD_HOST`/`MPD_PORT` match Mopidy's MPD frontend (default port 6600) |
