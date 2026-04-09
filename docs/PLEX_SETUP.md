# Plex Development Server Setup

This guide sets up a local Plex Media Server using Docker for development and testing of hello-operator.

---

## Prerequisites

### 1. Install Docker

Docker must be installed and running on your machine.

- **Mac**: Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- **Linux**: Install Docker Engine and the Docker Compose plugin via your package manager:
  ```bash
  # Debian/Ubuntu
  sudo apt install docker.io docker-compose-plugin
  sudo systemctl enable --now docker
  sudo usermod -aG docker $USER   # log out and back in after this
  ```
- **Windows**: Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)

Verify the installation:
```bash
docker compose version
```

### 2. Create a Plex account

A free Plex account is required to activate the server.

Sign up at [plex.tv](https://www.plex.tv) if you do not already have one.

### 3. Add music files

The Docker container serves media from `./plex/media/` in the project directory. Create that folder and copy some music into it before starting the server:

```bash
mkdir -p plex/media
cp -r /path/to/your/music plex/media/
```

Any folder structure works. Plex will scan recursively for audio files.

---

## First-Time Setup

### Step 1 — Get a claim token

A claim token links the new server to your Plex account. Tokens expire after **4 minutes**, so generate one immediately before running the container.

1. Log in to [plex.tv/claim](https://www.plex.tv/claim)
2. Copy the token (it looks like `claim-xxxxxxxxxxxxxxxxxxxx`)

### Step 2 — Start the container

From the project root, run:

```bash
PLEX_CLAIM=claim-xxxxxxxxxxxxxxxxxxxx docker compose up -d
```

Replace the token value with the one you just copied. Docker will pull the Plex image on first run, which may take a minute.

### Step 3 — Complete setup in the browser

1. Open [http://localhost:32400/web](http://localhost:32400/web)
2. Sign in with your Plex account when prompted
3. Name your server (anything you like)
4. Add a Music library:
   - Click **Add Library** → **Music**
   - Set the folder to `/data` (this maps to `./plex/media/` on your machine)
   - Click **Add Library**
5. Plex will scan and index your music — this may take a moment

---

## Subsequent Runs

The claim token is only needed once. After the first setup, start and stop the server with:

```bash
docker compose up -d     # start
docker compose down      # stop
```

The server configuration is persisted in `./plex/config/` and survives restarts.

---

## Configure hello-operator

Once the server is running, set the required environment variables in a `.env` file at the project root. Copy the example file to get started:

```bash
cp .env.example .env
```

Then edit `.env`:

```
PLEX_URL=http://localhost:32400
PLEX_TOKEN=<your token>
PLEX_PLAYER_IDENTIFIER=<your player identifier>
```

### Finding your Plex token

1. Open [http://localhost:32400/web](http://localhost:32400/web) and browse to any media item
2. Click the **⋮** menu → **Get Info** → **View XML**
3. Copy the `X-Plex-Token` value from the URL in the address bar

Alternatively, the Plex support article [Finding an authentication token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/) describes several methods.

### Finding your player identifier

The player identifier is the string Plex uses to target a specific playback client (e.g., the Raspberry Pi running hello-operator, or a desktop Plex player for testing).

1. Open a Plex client (desktop app, web player, or the Pi) and begin playing something, or leave it open
2. Fetch the list of active clients:
   ```bash
   curl -s "http://localhost:32400/clients" \
     -H "X-Plex-Token: <your token>" | grep -o 'machineIdentifier="[^"]*"'
   ```
3. Copy the identifier that matches your target player

---

## Troubleshooting

**Container starts but `http://localhost:32400/web` doesn't load**
Wait 10–15 seconds after `docker compose up -d` for Plex to initialise, then refresh.

**"Server not found" after opening the browser**
The claim token may have expired before the container started. Stop the container, get a fresh token, and run Step 2 again:
```bash
docker compose down
PLEX_CLAIM=claim-xxxxxxxxxxxxxxxxxxxx docker compose up -d
```

**Music not appearing in the library**
Check that your files are inside `./plex/media/` and are in a supported audio format (MP3, FLAC, AAC, etc.). Trigger a manual scan from **Settings → Troubleshooting → Clean Bundles** or by clicking **Scan Library Files** on the library.

**`docker compose` not found**
You may have an older Docker installation with a standalone `docker-compose` binary. Either upgrade Docker, or replace `docker compose` with `docker-compose` in all commands above.
