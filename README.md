# Hello Operator

A vintage rotary phone wired to a Raspberry Pi 4 that acts as a hands-on interface for a Plex media server. Picking up the handset triggers an interactive voice menu — styled as a telephone operator experience — where you browse and play playlists, artists, albums, and genres by dialing.

---

## How it works

| Action | Result |
|---|---|
| Lift handset | Dial tone → operator greeting → main menu |
| Dial `1`–`8` | Select the Nth menu option |
| Dial `0` | Return to top / main menu |
| Dial `9` | Go back one level |
| Dial two digits within 300 ms | Enter direct-dial mode |
| Direct-dial a 7-digit number | Connect directly to a media item or radio station |
| Replace handset | Stop local audio (music keeps playing on Plex) |

All menus are spoken aloud. There are no screens.

---

## Hardware

| Component | Purpose |
|---|---|
| Raspberry Pi 4 | Runs the software |
| Vintage rotary phone | Handset, speaker, dial |
| Adafruit MAX98357A I2S amplifier | Drives the handset speaker |
| Hook switch → GPIO | Detects handset up/down |
| Rotary dial → IR breakbeam → GPIO | Decodes dialed digits |
| RTL-SDR USB dongle (optional) | FM radio via `rtl_fm` |

Setup guides for each hardware component are in `docs/`:

- [`docs/AMP_SETUP.md`](docs/AMP_SETUP.md) — MAX98357A I2S amplifier
- [`docs/BREAKBEAM_SETUP.md`](docs/BREAKBEAM_SETUP.md) — IR breakbeam pulse switch
- [`docs/HOOK_SWITCH_SETUP.md`](docs/HOOK_SWITCH_SETUP.md) — hook switch
- [`docs/PIPER_SETUP.md`](docs/PIPER_SETUP.md) — Piper TTS voice engine
- [`docs/PLEX_SETUP.md`](docs/PLEX_SETUP.md) — Plex server configuration

---

## Installation

See [`INSTALL.md`](INSTALL.md) for the full guide.

**Option A — Flash a pre-built image (easiest)**

Download the latest `hello-operator-*.img.xz` from the [Releases](../../releases) page, flash it with [Raspberry Pi Imager](https://www.raspberrypi.com/software/), boot, edit `/etc/hello-operator/config.env`, and start the service. Everything else is pre-installed.

**Option B — Clone and install on a running Pi**

```bash
git clone <repo-url> hello-operator
cd hello-operator
sudo ./install.sh
# edit /etc/hello-operator/config.env
sudo systemctl start hello-operator
```

The install script handles system packages, the Piper TTS binary and voice model, the Python virtual environment, and the systemd service.

---

## Configuration

After installation, open the web interface from any device on the same network:

```
http://<pi-hostname>.local:8080
```

The default hostname on Raspberry Pi OS is `raspberrypi`, so the address is typically `http://raspberrypi.local:8080`. The web interface lets you configure all settings, browse documentation, and restart the service — no command line needed.

Settings are stored in `/etc/hello-operator/config.env` (owned by the `hello-operator` service account — use `sudo nano` to edit from the command line, or use the web UI). **Required:** `PLEX_TOKEN`, `PLEX_PLAYER_IDENTIFIER`, `ASSISTANT_NUMBER`. **Optional:** Plex URL, GPIO pin assignments, Piper paths, TTS cache directory, `ADMIN_PASSWORD` (password-protect the web UI). See [`INSTALL.md`](INSTALL.md) for the full table.

---

## Development

```bash
# Create and activate a virtual environment (required on Debian/Ubuntu/Pi OS,
# which block pip from installing into the system Python). When done, type `deactivate`.
python3 -m venv venv
source venv/bin/activate

# Install dev dependencies (no RPi.GPIO — not needed for tests)
pip install -r requirements-dev.txt

# Run all unit tests
python -m pytest -m "not integration" -v

# Run integration tests (requires live Plex server)
python -m pytest -m integration -v

# Run the app
python main.py
```

**Web interface local development** — two processes, one terminal each:

```bash
# Terminal 1 — Flask REST API on :8080 (Docker, recommended)
docker compose build web   # first time only, or after changing requirements-web.txt
docker compose up web

# Terminal 2 — Angular dev server on :4200 (proxies /api and /service to :8080)
cd web/angular
npm install          # first time only
npm start            # then open http://localhost:4200
```

The Flask container mounts the project root so doc pages are served live. Config is read from and written to `dev/config.env` (gitignored). To pre-populate it, copy the example:

```bash
cp config.env.example dev/config.env   # then fill in your values
```

**Without Docker** — run Flask directly instead of `docker compose up web`:

```bash
cp config.env.example dev/config.env
CONFIG_ENV_PATH=dev/config.env RADIO_JSON_PATH=dev/radio_stations.json python web/app.py
```

To build the Angular app for production (output served by Flask directly at :8080):

```bash
cd web/angular && npm run build
# Flask at :8080 now serves the full SPA
```

Tests use dependency injection via Python ABCs — no hardware or network required. GPIO, audio, TTS, and Plex are all mockable at the seam without patching.

`DOCS_ROOT` defaults to the project root, so the documentation pages work without any extra configuration. The service status and restart buttons will fail gracefully since `systemctl` is not available outside a Pi.

On a Raspberry Pi, install with `requirements-pi.txt` instead (adds `RPi.GPIO`).

---

## Project structure

```
src/
  main.py          # entry point — wires everything together
  session.py       # lifecycle: GPIO events → menu state machine
  menu.py          # state machine
  gpio_handler.py  # decodes raw GPIO pulses into events
  plex_client.py   # Plex HTTP API
  plex_store.py    # local SQLite browse cache
  phone_book.py    # maps 7-digit numbers to media items
  audio.py         # sounddevice audio output
  tts.py           # Piper TTS
  interfaces.py    # all ABCs and data types
  constants.py     # all configuration constants

web/
  app.py           # Flask REST API (port 8080)
  angular/         # Angular 21 SPA (StatusComponent, DocsComponent, ConfigComponent)

docs/
  DESIGN.md        # architecture and interface reference
  SCRIPTS.md       # all spoken TTS strings
  IMPL.md          # implementation order and status
```

---

## License

[MIT](LICENSE)
