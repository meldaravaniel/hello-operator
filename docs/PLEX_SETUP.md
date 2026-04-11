# Plex Setup

hello-operator requires a running Plex Media Server and a Plex account. Choose the setup path that fits your situation.

---

## Which path is right for you?

| Situation | Path |
|---|---|
| You want everything on the Pi and don't have a Plex server yet | [Install Plex on the Pi with Docker](#install-plex-on-the-pi-with-docker) |
| You already have Plex running on a NAS, PC, or another device | [Install Plex on another device](#install-plex-on-another-device) |

Either way, finish with [Configure hello-operator](#configure-hello-operator) once your server is up.

---

## Install Plex on the Pi with Docker

This runs Plex Media Server directly on the same Raspberry Pi as hello-operator, using the `docker-compose.yml` included in the project.

### Prerequisites

**1. Install Docker**

```bash
sudo apt install docker.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER   # log out and back in after this
```

Verify:
```bash
docker compose version
```

**2. Create a Plex account**

A free Plex account is required to activate the server. Sign up at [plex.tv](https://www.plex.tv) if you don't already have one.

**3. Add music files**

The container serves media from `./plex/media/` in the project directory. Create that folder and copy some music into it before starting:

```bash
mkdir -p plex/media
cp -r /path/to/your/music plex/media/
```

Any folder structure works — Plex scans recursively for audio files.

### First-time setup

**Step 1 — Get a claim token**

A claim token links the new server to your Plex account. Tokens expire after **4 minutes**, so generate one immediately before starting the container.

1. Log in to [plex.tv/claim](https://www.plex.tv/claim)
2. Copy the token (it looks like `claim-xxxxxxxxxxxxxxxxxxxx`)

**Step 2 — Start the container**

From the project root:

```bash
PLEX_CLAIM=claim-xxxxxxxxxxxxxxxxxxxx docker compose up -d
```

Replace the token with the one you just copied. Docker will pull the Plex image on the first run.

**Step 3 — Complete setup in the browser**

1. Open [http://localhost:32400/web](http://localhost:32400/web) (or `http://<pi-hostname>.local:32400/web` from another device)
2. Sign in with your Plex account when prompted
3. Name your server
4. Add a Music library: **Add Library → Music**, set the folder to `/data`, click **Add Library**
5. Plex will scan and index your music

### Subsequent runs

The claim token is only needed once. After first-time setup:

```bash
docker compose up -d     # start
docker compose down      # stop
```

Server configuration is persisted in `./plex/config/` and survives restarts.

### Troubleshooting

**`http://localhost:32400/web` doesn't load after starting**
Wait 10–15 seconds for Plex to initialise, then refresh.

**"Server not found" in the browser**
The claim token may have expired. Stop the container, get a fresh token, and restart:
```bash
docker compose down
PLEX_CLAIM=claim-xxxxxxxxxxxxxxxxxxxx docker compose up -d
```

**Music not appearing in the library**
Confirm your files are inside `./plex/media/` and are in a supported format (MP3, FLAC, AAC, etc.). Trigger a manual scan from the library's **⋮ menu → Scan Library Files**.

**`docker compose` not found**
You may have an older Docker installation. Either upgrade Docker, or replace `docker compose` with `docker-compose` in all commands above.

---

## Install Plex on another device

If you prefer to run Plex on a NAS, desktop, or another machine, follow [Plex's official installation guide](https://support.plex.tv/articles/200288586-installation/) for your platform.

Once installed, make a note of:
- The server's local IP address or hostname (e.g. `http://192.168.1.50:32400`)
- Your [Plex authentication token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)

Then continue to [Configure hello-operator](#configure-hello-operator) below.

---

## Configure hello-operator

Once your Plex server is running, provide its details to hello-operator via `/etc/hello-operator/config.env` (or through the web interface at `http://<pi-hostname>.local:8080`).

### Required values

**`PLEX_URL`**
The base URL of your Plex server. Use `http://localhost:32400` if Plex is running on the same Pi; otherwise use the server's local address:
```
PLEX_URL=http://192.168.1.50:32400
```

**`PLEX_TOKEN`**
Your Plex authentication token. See [Finding an authentication token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/) in the Plex support docs.

Quick method — browse to any media item in Plex Web, click **⋮ → Get Info → View XML**, and copy the `X-Plex-Token` value from the URL.

**`PLEX_PLAYER_IDENTIFIER`**
The machine identifier of the Plex player hello-operator should control (e.g. the Plex app running on the Pi, or a desktop player for testing). Fetch the list of active clients to find it:

```bash
curl -s "http://<plex-url>/clients" \
  -H "X-Plex-Token: <your token>" | grep -o 'machineIdentifier="[^"]*"'
```

The target Plex client must be open and visible to the server when you run this.
