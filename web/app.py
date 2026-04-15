"""hello-operator web configuration interface.

Pure REST API backend. Reads/writes /etc/hello-operator/config.env and
/etc/hello-operator/radio_stations.json, then restarts the hello-operator
systemd service as needed.

All UI is served by the Angular SPA built into web/angular/dist/.

Run via the hello-operator-web systemd service (see install.sh), or directly:
  WEB_PORT=8080 python web/app.py
"""

import json
import os
import re
import subprocess
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

# ---------------------------------------------------------------------------
# Paths (overridable via environment for local development)
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
_PROJECT_ROOT = _HERE.parent

CONFIG_ENV_PATH = Path(os.environ.get("CONFIG_ENV_PATH", "/etc/hello-operator/config.env"))
RADIO_JSON_PATH = Path(os.environ.get("RADIO_JSON_PATH", "/etc/hello-operator/radio_stations.json"))
DOCS_ROOT = Path(os.environ.get("DOCS_ROOT", str(_PROJECT_ROOT)))
ANGULAR_DIST = Path(os.environ.get("ANGULAR_DIST", str(_HERE / "angular" / "dist" / "hello-operator" / "browser")))
WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))

# ---------------------------------------------------------------------------
# Documentation pages (title, path relative to DOCS_ROOT)
# ---------------------------------------------------------------------------

DOC_PAGES = [
    ("Overview",         "README.md"),
    ("Installation",     "INSTALL.md"),
    ("Amplifier",        "docs/AMP_SETUP.md"),
    ("Breakbeam Switch", "docs/BREAKBEAM_SETUP.md"),
    ("Hook Switch",      "docs/HOOK_SWITCH_SETUP.md"),
    ("Piper TTS",        "docs/PIPER_SETUP.md"),
    ("Plex Setup",       "docs/PLEX_SETUP.md"),
]

# ---------------------------------------------------------------------------
# Configuration field definitions
# ---------------------------------------------------------------------------

# Sections that are only relevant when one of the listed backends is active.
# Fields in these sections skip required-validation for other backends.
BACKEND_SECTIONS: dict[str, list[str]] = {
    "Plex": ["plex"],
    "MPD":  ["mpd", "mopidy"],
}

CONFIG_FIELDS = [
    {
        "section": "Media Backend",
        "key": "MEDIA_BACKEND",
        "label": "Media Backend",
        "type": "select",
        "options": ["plex", "mpd", "mopidy"],
        "required": False,
        "default": "mpd",
        "help": "Which media player backend to use. "
                "'plex' connects to a Plex Media Server; "
                "'mpd' connects to a Music Player Daemon; "
                "'mopidy' connects to a Mopidy server via its MPD interface.",
    },
    {
        "section": "Plex",
        "key": "PLEX_TOKEN",
        "label": "Plex Token",
        "type": "password",
        "required": True,
        "help": "Your Plex authentication token. "
                "Find it at: Plex Web → Account → Authorized Devices.",
    },
    {
        "section": "Plex",
        "key": "PLEX_PLAYER_IDENTIFIER",
        "label": "Plex Player Identifier",
        "type": "text",
        "required": True,
        "help": "Machine identifier of the Plex player to control. "
                "Find it in Plex Web → Settings → Troubleshooting.",
    },
    {
        "section": "Plex",
        "key": "PLEX_URL",
        "label": "Plex Server URL",
        "type": "url",
        "required": False,
        "default": "http://localhost:32400",
        "help": "Full URL of your Plex Media Server. "
                "Change this if your Plex server runs on a different machine.",
    },
    {
        "section": "MPD",
        "key": "MPD_HOST",
        "label": "MPD Host",
        "type": "text",
        "required": False,
        "default": "localhost",
        "help": "Hostname or IP address of the Music Player Daemon. "
                "Only used when MEDIA_BACKEND is 'mpd'.",
    },
    {
        "section": "MPD",
        "key": "MPD_PORT",
        "label": "MPD Port",
        "type": "number",
        "required": False,
        "default": "6600",
        "help": "TCP port on which MPD is listening. Default is 6600. "
                "Only used when MEDIA_BACKEND is 'mpd'.",
    },
    {
        "section": "Phone System",
        "key": "ASSISTANT_NUMBER",
        "label": "Assistant Phone Number",
        "type": "tel",
        "required": True,
        "help": "7-digit number reserved for the diagnostic assistant "
                "(e.g. 5550000). Must not conflict with any auto-assigned media number.",
    },
    {
        "section": "GPIO",
        "key": "HOOK_SWITCH_PIN",
        "label": "Hook Switch GPIO Pin",
        "type": "number",
        "required": False,
        "default": "17",
        "help": "BCM GPIO pin for the hook switch. Default matches the wiring guide.",
    },
    {
        "section": "GPIO",
        "key": "PULSE_SWITCH_PIN",
        "label": "Pulse Switch GPIO Pin",
        "type": "number",
        "required": False,
        "default": "27",
        "help": "BCM GPIO pin for the rotary pulse switch. Default matches the wiring guide.",
    },
    {
        "section": "TTS",
        "key": "PIPER_BINARY",
        "label": "Piper Binary Path",
        "type": "text",
        "required": False,
        "default": "/usr/local/bin/piper",
        "help": "Absolute path to the Piper TTS executable.",
    },
    {
        "section": "TTS",
        "key": "PIPER_MODEL",
        "label": "Piper Voice Model",
        "type": "text",
        "required": False,
        "default": "/usr/local/share/piper/en_US-lessac-medium.onnx",
        "help": "Absolute path to the Piper .onnx voice model file.",
    },
    {
        "section": "TTS",
        "key": "TTS_CACHE_DIR",
        "label": "TTS Cache Directory",
        "type": "text",
        "required": False,
        "default": "/var/cache/hello-operator/tts",
        "help": "Directory where pre-rendered TTS audio files are stored.",
    },
]

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Config I/O helpers
# ---------------------------------------------------------------------------


def read_config_env() -> dict:
    """Return a dict of KEY → value parsed from config.env.

    Comments and blank lines are ignored. Surrounding quotes are stripped
    from values (systemd EnvironmentFile allows KEY="value" syntax).
    """
    values: dict = {}
    try:
        with CONFIG_ENV_PATH.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"')
    except FileNotFoundError:
        pass
    return values


def write_config_env(updates: dict) -> None:
    """Update config.env in-place, preserving comments and structure.

    Existing KEY=value lines are replaced with the new value.
    Keys not yet present are appended at the end of the file.
    All values are written as KEY="value" (quoted) so spaces and most
    special characters are handled correctly by systemd EnvironmentFile.
    """
    try:
        with CONFIG_ENV_PATH.open() as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    written: set = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in updates:
                escaped = updates[key].replace("\\", "\\\\").replace('"', '\\"')
                new_lines.append(f'{key}="{escaped}"\n')
                written.add(key)
                continue
        new_lines.append(line)

    for key, value in updates.items():
        if key not in written:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            new_lines.append(f'{key}="{escaped}"\n')

    with CONFIG_ENV_PATH.open("w") as f:
        f.writelines(new_lines)


def read_radio_stations() -> list:
    """Return the list of radio station dicts from radio_stations.json."""
    try:
        with RADIO_JSON_PATH.open() as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def write_radio_stations(stations: list) -> None:
    """Write a list of station dicts to radio_stations.json."""
    with RADIO_JSON_PATH.open("w") as f:
        json.dump(stations, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------


def get_service_status() -> str:
    """Return the systemd active state of hello-operator (e.g. 'active')."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "hello-operator"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def restart_service() -> tuple[bool, str]:
    """Restart the hello-operator service via sudo systemctl.

    Returns (success, error_message).
    Requires a sudoers rule allowing the web server's user to run:
      sudo systemctl restart hello-operator
    without a password (installed by install.sh / build-image-chroot.sh).
    """
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", "hello-operator"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return result.returncode == 0, result.stderr.strip()
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Doc helpers
# ---------------------------------------------------------------------------


def _doc_list() -> list[tuple[str, str]]:
    """Return (title, slug) for each doc page that exists on disk."""
    result = []
    for title, rel_path in DOC_PAGES:
        if (DOCS_ROOT / rel_path).exists():
            slug = rel_path.replace("/", "_").replace(".md", "")
            result.append((title, slug))
    return result


def _slug_to_path(slug: str) -> str | None:
    for _, rel_path in DOC_PAGES:
        if rel_path.replace("/", "_").replace(".md", "") == slug:
            return rel_path
    return None


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.route("/api/status")
def api_status():
    return jsonify({"status": get_service_status()})


@app.route("/service/restart", methods=["POST"])
def service_restart():
    ok, err = restart_service()
    return jsonify({"ok": ok, "error": err if not ok else None, "status": get_service_status()})


@app.route("/api/docs")
def api_docs_list():
    pages = [{"title": t, "slug": s} for t, s in _doc_list()]
    return jsonify({"pages": pages})


@app.route("/api/docs/<slug>")
def api_docs_page(slug: str):
    rel_path = _slug_to_path(slug)
    if not rel_path or not (DOCS_ROOT / rel_path).exists():
        return jsonify({"error": "Page not found"}), 404
    content = (DOCS_ROOT / rel_path).read_text()
    title = next(t for t, p in DOC_PAGES if p == rel_path)
    return jsonify({"title": title, "slug": slug, "content": content})


@app.route("/api/config")
def api_config_get():
    all_values = read_config_env()
    # Omit password field values from the response
    password_keys = {f["key"] for f in CONFIG_FIELDS if f["type"] == "password"}
    values = {k: v for k, v in all_values.items() if k not in password_keys}
    return jsonify({
        "fields": CONFIG_FIELDS,
        "values": values,
        "stations": read_radio_stations(),
    })


@app.route("/api/config/env", methods=["POST"])
def api_config_env():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"ok": False, "errors": ["Invalid JSON body."]}), 400

    updates: dict = {}
    errors: list = []

    backend = str(payload.get("MEDIA_BACKEND", "mpd")).strip() or "mpd"

    for field in CONFIG_FIELDS:
        key = field["key"]
        value = str(payload.get(key, "")).strip()
        # Skip required-validation for fields that belong to a non-selected backend.
        required_backends = BACKEND_SECTIONS.get(field["section"])
        if required_backends and backend not in required_backends:
            if value:
                updates[key] = value
            continue
        # Password fields: blank means "keep current value"
        if field["type"] == "password" and not value:
            continue
        if field["required"] and not value:
            errors.append(f"{field['label']} is required.")
            continue
        if value:
            updates[key] = value

    if errors:
        return jsonify({"ok": False, "errors": errors}), 422

    write_config_env(updates)
    ok, err = restart_service()
    msg = "Settings saved and service restarted." if ok else f"Settings saved. Restart failed: {err}"
    return jsonify({"ok": True, "message": msg})


@app.route("/api/config/radio", methods=["POST"])
def api_config_radio():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"ok": False, "errors": ["Invalid JSON body."]}), 400

    stations: list = []
    errors: list = []

    for i, item in enumerate(payload, start=1):
        name = str(item.get("name", "")).strip()
        phone = str(item.get("phone_number", "")).strip()
        try:
            freq = float(item.get("frequency_mhz", 0))
        except (ValueError, TypeError):
            errors.append(f"Station {i}: frequency must be a number.")
            continue
        if not name:
            errors.append(f"Station {i}: name is required.")
            continue
        if not re.fullmatch(r"\d{7}", phone):
            errors.append(f"Station {i}: phone number must be exactly 7 digits.")
            continue
        if freq <= 0:
            errors.append(f"Station {i}: frequency must be positive.")
            continue
        stations.append({"name": name, "frequency_mhz": freq, "phone_number": phone})

    if errors:
        return jsonify({"ok": False, "errors": errors}), 422

    write_radio_stations(stations)
    ok, err = restart_service()
    msg = "Radio stations saved and service restarted." if ok else f"Radio stations saved. Restart failed: {err}"
    return jsonify({"ok": True, "message": msg})


# ---------------------------------------------------------------------------
# Angular SPA catch-all
# ---------------------------------------------------------------------------


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_spa(path: str):
    # Let defined API routes handle their own 404s
    if path.startswith(("api/", "service/", "config/")):
        abort(404)

    if ANGULAR_DIST.is_dir():
        target = ANGULAR_DIST / path
        if path and target.is_file():
            return send_from_directory(str(ANGULAR_DIST), path)
        index = ANGULAR_DIST / "index.html"
        if index.exists():
            return send_from_directory(str(ANGULAR_DIST), "index.html")

    return (
        "<html><body><h1>Frontend not built</h1>"
        "<p>Run: <code>cd web/angular &amp;&amp; npm install &amp;&amp; ng build</code></p>"
        "</body></html>"
    ), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False)
