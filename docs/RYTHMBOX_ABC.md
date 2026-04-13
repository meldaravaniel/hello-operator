# Rhythmbox as an Alternative Media Backend

## Short answer: Architecturally yes, practically challenging

The interface seam already exists — `PlexClientInterface` in `src/interfaces.py` is exactly the right place to plug in an alternative. Everything above it (`menu`, `plex_store`, `session`) only talks to that interface, never to `PlexClient` directly. A `RhythmboxClient` implementing the same ABC would slot right into `main.py`.

## What would map cleanly

Rhythmbox exposes MPRIS2 via D-Bus, so these methods translate directly:

| Interface method | Rhythmbox equivalent |
|---|---|
| `play()`, `pause()`, `unpause()`, `stop()`, `skip()` | MPRIS2 `org.mpris.MediaPlayer2.Player` |
| `shuffle_all()` | MPRIS2 `Shuffle=true` + `Play` |
| `now_playing()` | MPRIS2 `Metadata` property |
| `get_playlists()`, `get_artists()`, `get_genres()` | `org.gnome.Rhythmbox3.RhythmDB` queries |

## Where it gets awkward

1. **Genre key encoding** — the genre `plex_key` format `"section:{section_id}/genre:{genre_key}"` is baked into `menu._parse_genre_plex_key()`. A Rhythmbox adapter would need to encode something compatible, or the menu would need a second parsing path.

2. **`get_tracks_for_genre(section_id, genre_key)`** — `section_id` is a Plex concept (music library sections). Rhythmbox has no equivalent; the adapter would ignore it, making the signature misleading.

3. **`play_tracks(track_keys, shuffle)`** — track keys are Plex integer `ratingKey` values stored in the phone book. For Rhythmbox these would need to be D-Bus entry IDs or `file://` URIs. The phone book stores whatever is in `MediaItem.plex_key`, so the key format would change — that works, but the field name `plex_key` becomes a misnomer throughout.

4. **`get_queue_position()`** — Rhythmbox doesn't expose a numeric queue position via MPRIS2; you'd return a stub like `(0, 0)` and queue position announcements in the menu would silently break.

## The biggest practical blocker

Rhythmbox is a GTK desktop application. It needs a D-Bus **session** bus and a display. On a headless Pi this means running it inside a virtual framebuffer (e.g. `Xvfb`) or using `rhythmbox --no-ui` (which exists but is poorly maintained). Plex by contrast runs as a server daemon with no display dependency.

## What would need to change if you went ahead

- Rename `PlexClientInterface` → `MediaClientInterface` and the Plex-specific parameter names throughout (cosmetic but worthwhile)
- Generalize `get_tracks_for_genre` signature (e.g. drop `section_id`, or make it an optional kwargs)
- Add a `MEDIA_BACKEND` env var to `constants.py` and a factory in `main.py` that picks `PlexClient` vs `RhythmboxClient`
- Write `RhythmboxClient` implementing all 13 methods via D-Bus subprocess calls or `dbus-python`
- Decide what to do about `get_queue_position()` — stub or skip that menu feature
