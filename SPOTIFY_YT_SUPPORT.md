# Spotify and YouTube Music Support via Mopidy

## Overview

Both Spotify and YouTube Music can be added as hello-operator backends by running Mopidy with the `mopidy-spotify` or `mopidy-ytmusic` extension and having hello-operator talk to Mopidy's **JSON-RPC API** rather than the MPD wire protocol.

This is the key architectural choice. The MPD protocol (used by the current `MPDClient`) exposes a flat library view that doesn't map well to Spotify or YouTube Music concepts — there's no native "followed artists" or "followed playlists" concept. Mopidy's JSON-RPC API (`http://{host}:6680/mopidy/rpc`) exposes the full virtual file system of each extension, including user-specific data like saved playlists and, to varying degrees, followed artists.

**Authentication is handled entirely by the Mopidy extensions**, not by hello-operator. The user configures Spotify OAuth credentials in `/etc/mopidy/mopidy.conf`; mopidy-spotify manages token refresh. For YouTube Music, the user generates OAuth credentials once using `ytmusicapi browser` and mopidy-ytmusic loads them from a JSON file. hello-operator never touches credentials directly.

---

## How it fits the current architecture

The existing `MediaClientInterface` ABC covers everything needed. Two new concrete implementations would be added:

- `SpotifyMopidyClient` — browses `spotify:` URIs via Mopidy JSON-RPC
- `YouTubeMopidyClient` — browses `ytmusic:` URIs via Mopidy JSON-RPC

Both share a base helper class (`MopidyRpcClient`) that handles the HTTP JSON-RPC connection and the common playback operations (`play`, `pause`, `next`, `stop`, `tracklist.clear`, `tracklist.add`, etc.). Browse operations are extension-specific and live in the subclass.

`MEDIA_BACKEND=spotify` and `MEDIA_BACKEND=ytmusic` would be the two new values, wired up in `build_media_client()` in `main.py`.

The rest of the stack — `MediaStore`, `PhoneBook`, `Menu`, `Session` — is unaffected.

---

## The scoping strategy

Spotify and YouTube Music catalogs are enormous. The user's instinct is correct: without scoping, `get_artists()` could return thousands of results or time out entirely.

The proposed scope: **followed/saved playlists + manually curated artists and playlists**.

### Playlists

- **Spotify**: mopidy-spotify exposes the user's saved playlists at `spotify:user:playlists`. Browsing that URI returns the list. This works today.
- **YouTube Music**: mopidy-ytmusic exposes library playlists at `ytmusic:library:playlists`. This works today.

### Artists

This is harder. Neither extension cleanly exposes "followed artists" through the virtual file system. The Spotify Web API has a `GET /me/following?type=artist` endpoint, but accessing it directly would require hello-operator to hold Spotify API credentials and make its own OAuth calls — a significant addition.

**Recommended approach: manual curation only for artists**, with a curated library config file (`/etc/hello-operator/curated_library.json`):

```json
{
  "spotify": {
    "artists": [
      { "name": "Radiohead", "uri": "spotify:artist:4Z8W4fKeB5YxbusRsdQVPb" },
      { "name": "Tame Impala" }
    ],
    "playlists": [
      { "name": "Road Trip", "uri": "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M" }
    ]
  },
  "ytmusic": {
    "artists": [
      { "name": "Bonobo", "uri": "ytmusic:artist:UCpQPjXFuVfHKMKBDaGUrnQ" }
    ],
    "playlists": [
      { "name": "Chill Mix", "uri": "ytmusic:playlist:RDCLAK5uy_..." }
    ]
  }
}
```

When a URI is provided, it's used directly. When only a name is given, the client performs a Mopidy search at startup to resolve it to a URI. Unresolvable names are logged as warnings and skipped.

`get_artists()` returns only the curated list. `get_playlists()` returns curated playlists merged with the user's saved/followed playlists from the API.

### Genres

Spotify's genre data lives on artist objects (e.g., "indie rock", "dream pop") — there's no per-track genre field. YouTube Music has no genre concept at all. `get_genres()` returns `[]` for both backends. The genre menu option is suppressed when the genre list is empty — this already works in the current menu implementation.

---

## New components

### `src/mopidy_rpc.py` — shared JSON-RPC base

A plain HTTP client that POSTs to `http://{host}:{port}/mopidy/rpc`. No WebSocket needed — hello-operator is a request/response caller, not an event subscriber. Methods:

- `browse(uri)` → list of `Ref` objects (`{uri, name, type}`)
- `search(query, uris)` → search results
- `get_state()` → `"playing"`, `"paused"`, `"stopped"`
- `get_current_track()` → current track dict or `None`
- `tracklist_clear()`, `tracklist_add(uris)`, `tracklist_shuffle()`
- `playback_play()`, `playback_pause()`, `playback_resume()`, `playback_next()`, `playback_stop()`
- `get_tracklist_length()`, `get_tracklist_index()`

### `src/spotify_client.py` — `SpotifyMopidyClient`

Implements `MediaClientInterface`. Media key format mirrors the Mopidy URI:

| Type | `media_key` |
|---|---|
| Playlist | `spotify:playlist:{id}` |
| Artist | `spotify:artist:{id}` |
| Album | `spotify:album:{id}` |
| Track | `spotify:track:{id}` |

- `get_playlists()` → browse `spotify:user:playlists` + curated playlists
- `get_artists()` → curated artists only (resolved to URIs at startup)
- `get_albums_for_artist(key)` → browse `spotify:artist:{id}`
- `get_tracks_for_genre(key)` → always returns `[]` (genres not supported)
- `play(key)` → `tracklist.clear()` + `tracklist.add([key])` + `playback.play()`
- `play_tracks(keys, shuffle)` → `tracklist.clear()` + `tracklist.add(keys)` + optional shuffle + `playback.play()`
- `shuffle_all()` → load user's saved playlists, add all tracks, shuffle, play — or simply shuffle the tracklist if already populated

### `src/ytmusic_client.py` — `YouTubeMopidyClient`

Same structure. Media key format:

| Type | `media_key` |
|---|---|
| Playlist | `ytmusic:playlist:{id}` |
| Artist | `ytmusic:artist:{channelId}` |
| Album | `ytmusic:album:{browseId}` |
| Track | `ytmusic:track:{videoId}` |

- `get_playlists()` → browse `ytmusic:library:playlists` + curated playlists
- `get_artists()` → curated artists only
- `get_albums_for_artist(key)` → browse `ytmusic:artist:{channelId}`
- `get_tracks_for_genre(key)` → `[]`
- Playback same as Spotify client

---

## Configuration changes

### New constants (`src/constants.py`)

| Constant | Default | Notes |
|---|---|---|
| `MOPIDY_RPC_HOST` | `localhost` | Mopidy JSON-RPC host |
| `MOPIDY_RPC_PORT` | `6680` | Mopidy JSON-RPC port |
| `CURATED_LIBRARY_PATH` | `/etc/hello-operator/curated_library.json` | Curated artists and playlists |

`MOPIDY_RPC_HOST` and `MOPIDY_RPC_PORT` are separate from the existing `MPD_HOST`/`MPD_PORT` because a user might run Mopidy alongside a plain MPD instance.

### `config.env.example`

New optional section for Spotify/YouTube Music backends.

### `install.sh`

Add notes about `mopidy-spotify` and `mopidy-ytmusic`. These are pip packages installed into Mopidy's own environment, not into hello-operator's virtualenv. The install script can print setup instructions but should not attempt to install them automatically, since Mopidy manages its own plugin system.

---

## Web UI changes

### New config sections

The Configure page gains two new sections, visible only for their respective backends:

**Spotify** (visible when `MEDIA_BACKEND=spotify`):
- Mopidy RPC host and port
- Read-only note: "Spotify credentials are configured in `/etc/mopidy/mopidy.conf`"
- Curated artists editor (same UX as radio stations: name + optional URI, add/remove rows)
- Curated playlists editor (name + URI)

**YouTube Music** (visible when `MEDIA_BACKEND=ytmusic`):
- Mopidy RPC host and port
- Read-only note: "YouTube Music credentials are managed by mopidy-ytmusic"
- Curated artists editor
- Curated playlists editor

### New API endpoints (`web/app.py`)

| Endpoint | Method | Description |
|---|---|---|
| `/api/config/curated` | GET | Return curated library for the current backend |
| `/api/config/curated` | POST | Save curated library JSON |

The GET response includes the current backend so the UI knows which fields to show.

### `BACKEND_SECTIONS` in Angular

Add `'Spotify': ['spotify']` and `'YouTube Music': ['ytmusic']` to the existing map.

---

## Work breakdown

Rough ordering by dependency:

1. **`src/mopidy_rpc.py`** — base RPC class and tests (mock HTTP responses)
2. **`src/spotify_client.py`** and **`tests/test_spotify_client.py`** — browse + playback, mock RPC
3. **`src/ytmusic_client.py`** and **`tests/test_ytmusic_client.py`** — same structure
4. **Curated library format** — define the JSON schema, `load_curated_library()` helper in `main.py` (mirrors `load_radio_stations()`), tests
5. **`src/constants.py`** — `MOPIDY_RPC_HOST`, `MOPIDY_RPC_PORT`, `CURATED_LIBRARY_PATH`
6. **`main.py`** — wire `spotify` and `ytmusic` into `build_media_client()`
7. **`web/app.py`** — add Spotify and YouTube Music config sections, `/api/config/curated` endpoints
8. **Angular** — new config sections with curated artist/playlist editors, `BACKEND_SECTIONS` update
9. **`install.sh`** / **`INSTALL.md`** / **`config.env.example`** — documentation and setup notes

Integration tests for both clients would require a live Mopidy instance with the respective extension configured and authenticated — marked `@pytest.mark.integration` and skipped by default, same as the existing Plex integration tests.

---

## Risks and open questions

**mopidy-spotify followed artists** — The extension may not expose followed artists through `core.library.browse()` at all. If `spotify:user:following` is not a browsable URI, artists can only come from the curated list. This is the most likely limitation to hit in practice; manual curation is the designed fallback.

**mopidy-ytmusic subscriptions** — Same uncertainty for YouTube channel subscriptions. The extension's virtual file system varies by version. Needs verification against the current mopidy-ytmusic release.

**Spotify Premium required** — mopidy-spotify requires a Spotify Premium account for playback. Free accounts can browse but not stream. Worth surfacing clearly in setup docs.

**YouTube Music Terms of Service** — ytmusicapi (which mopidy-ytmusic uses internally) is an unofficial API client. YouTube has historically tolerated it but does not officially support it. Sessions may expire or break with YouTube changes. This is mopidy-ytmusic's problem to solve, not hello-operator's, but users should understand the dependency.

**URI resolution at startup** — Resolving artist names to URIs via `core.library.search()` requires Mopidy to be running when hello-operator starts. If Mopidy is unavailable, startup should log a warning and continue with an empty artist list rather than failing hard — consistent with how `MediaStore` handles failed refreshes.

**`shuffle_all()` scope** — For Spotify and YouTube Music, "shuffle all" is ambiguous. A reasonable default: shuffle all tracks across all curated playlists. This needs a concrete definition before implementation.

**Mopidy JSON-RPC port conflicts** — The default Mopidy JSON-RPC port (6680) is separate from the MPD port (6600). Users running both MPD and Mopidy on the same host need to ensure no conflicts. `MOPIDY_RPC_HOST`/`MOPIDY_RPC_PORT` being distinct constants from `MPD_HOST`/`MPD_PORT` handles this.
