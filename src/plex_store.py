"""Local Plex cache for hello-operator.

PlexStore is a persistent, session-independent SQLite cache that sits between
the menu and plex_client.  The menu never calls plex_client directly for browse
data — it always goes through PlexStore.

Data model (plex_cache table):
    cache_key  TEXT PRIMARY KEY  -- e.g. "playlists", "albums:/artists/10"
    data       TEXT NOT NULL     -- JSON-serialized list of MediaItems
    updated_at TEXT NOT NULL     -- ISO8601 timestamp of last successful sync
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.interfaces import MediaItem, PlexClientInterface


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(items: List[MediaItem]) -> str:
    return json.dumps([
        {"plex_key": i.plex_key, "name": i.name, "media_type": i.media_type}
        for i in items
    ])


def _deserialize(data: str) -> List[MediaItem]:
    return [
        MediaItem(plex_key=d["plex_key"], name=d["name"], media_type=d["media_type"])
        for d in json.loads(data)
    ]


_KEY_PLAYLISTS = "playlists"
_KEY_ARTISTS = "artists"
_KEY_GENRES = "genres"


def _albums_key(artist_key: str) -> str:
    return f"albums:{artist_key}"


class MockPlexStore:
    """In-memory mock for unit tests. Configurable and records calls."""

    def __init__(self) -> None:
        self._playlists: List[MediaItem] = []
        self._artists: List[MediaItem] = []
        self._genres: List[MediaItem] = []
        self._albums: Dict[str, List[MediaItem]] = {}
        self.calls: list = []
        self._refresh_result: Dict[str, str] = {'playlists': 'ok', 'artists': 'ok', 'genres': 'ok'}

    # -- Configuration (test-only) ------------------------------------------
    def set_playlists(self, items: List[MediaItem]) -> None:
        self._playlists = list(items)

    def set_artists(self, items: List[MediaItem]) -> None:
        self._artists = list(items)

    def set_genres(self, items: List[MediaItem]) -> None:
        self._genres = list(items)

    def set_albums_for_artist(self, artist_key: str, albums: List[MediaItem]) -> None:
        self._albums[artist_key] = list(albums)

    def set_refresh_result(self, result: Dict[str, str]) -> None:
        self._refresh_result = result

    # -- PlexStore interface -------------------------------------------------
    @property
    def playlists_has_content(self) -> bool:
        return bool(self._playlists)

    @property
    def artists_has_content(self) -> bool:
        return bool(self._artists)

    @property
    def genres_has_content(self) -> bool:
        return bool(self._genres)

    def get_playlists(self) -> List[MediaItem]:
        self.calls.append(('get_playlists',))
        return list(self._playlists)

    def get_artists(self) -> List[MediaItem]:
        self.calls.append(('get_artists',))
        return list(self._artists)

    def get_genres(self) -> List[MediaItem]:
        self.calls.append(('get_genres',))
        return list(self._genres)

    def get_albums_for_artist(self, artist_key: str) -> List[MediaItem]:
        self.calls.append(('get_albums_for_artist', artist_key))
        return list(self._albums.get(artist_key, []))

    def remove_item(self, plex_key: str) -> None:
        self.calls.append(('remove_item', plex_key))
        self._playlists = [i for i in self._playlists if i.plex_key != plex_key]
        self._artists = [i for i in self._artists if i.plex_key != plex_key]
        self._genres = [i for i in self._genres if i.plex_key != plex_key]
        for k in list(self._albums):
            self._albums[k] = [i for i in self._albums[k] if i.plex_key != plex_key]

    def refresh(self) -> Dict[str, str]:
        self.calls.append(('refresh',))
        return dict(self._refresh_result)


class PlexStore:
    """Persistent local cache of Plex browse data."""

    def __init__(self, db_path: str, plex_client: PlexClientInterface) -> None:
        self._db_path = db_path
        self._plex_client = plex_client
        self._init_db()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plex_cache (
                    cache_key  TEXT PRIMARY KEY,
                    data       TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    # ------------------------------------------------------------------
    # Private DB helpers
    # ------------------------------------------------------------------

    def _read(self, cache_key: str) -> Optional[List[MediaItem]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM plex_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        if row is None:
            return None
        return _deserialize(row["data"])

    def _write(self, cache_key: str, items: List[MediaItem]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO plex_cache (cache_key, data, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                """,
                (cache_key, _serialize(items), _now_iso()),
            )

    def _delete_item(self, cache_key: str, plex_key: str) -> None:
        """Remove a single item from a cached list."""
        existing = self._read(cache_key)
        if existing is None:
            return
        updated = [i for i in existing if i.plex_key != plex_key]
        self._write(cache_key, updated)

    def _all_album_keys(self) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT cache_key FROM plex_cache WHERE cache_key LIKE 'albums:%'"
            ).fetchall()
        return [r["cache_key"] for r in rows]

    # ------------------------------------------------------------------
    # Public properties (has_content flags)
    # ------------------------------------------------------------------

    def _has_content(self, cache_key: str) -> bool:
        """Return True if cache_key exists and its data is not '[]'."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM plex_cache WHERE cache_key = ? AND data != '[]'",
                (cache_key,),
            ).fetchone()
        return row is not None

    @property
    def playlists_has_content(self) -> bool:
        return self._has_content(_KEY_PLAYLISTS)

    @property
    def artists_has_content(self) -> bool:
        return self._has_content(_KEY_ARTISTS)

    @property
    def genres_has_content(self) -> bool:
        return self._has_content(_KEY_GENRES)

    # ------------------------------------------------------------------
    # Browse data accessors
    # ------------------------------------------------------------------

    def get_playlists(self) -> List[MediaItem]:
        return self._get_or_fetch(_KEY_PLAYLISTS, self._plex_client.get_playlists)

    def get_artists(self) -> List[MediaItem]:
        return self._get_or_fetch(_KEY_ARTISTS, self._plex_client.get_artists)

    def get_genres(self) -> List[MediaItem]:
        return self._get_or_fetch(_KEY_GENRES, self._plex_client.get_genres)

    def get_albums_for_artist(self, artist_key: str) -> List[MediaItem]:
        key = _albums_key(artist_key)
        return self._get_or_fetch(key, lambda: self._plex_client.get_albums_for_artist(artist_key))

    def _get_or_fetch(self, cache_key: str, fetch_fn) -> List[MediaItem]:
        """Return local data if available; otherwise fetch, store, and return."""
        cached = self._read(cache_key)
        if cached is not None:
            return cached
        # Fetch from Plex
        items = fetch_fn()
        self._write(cache_key, items)
        return items

    # ------------------------------------------------------------------
    # Item removal (on playback not-found)
    # ------------------------------------------------------------------

    def remove_item(self, plex_key: str) -> None:
        """Remove an item from all cached lists (called when Plex reports not found)."""
        for key in [_KEY_PLAYLISTS, _KEY_ARTISTS, _KEY_GENRES] + self._all_album_keys():
            self._delete_item(key, plex_key)

    # ------------------------------------------------------------------
    # Manual refresh
    # ------------------------------------------------------------------

    def refresh(self) -> Dict[str, str]:
        """Re-fetch all categories from Plex. Returns {category: 'ok'|'error'}."""
        summary: Dict[str, str] = {}

        for category_name, cache_key, fetch_fn in [
            ("playlists", _KEY_PLAYLISTS, self._plex_client.get_playlists),
            ("artists", _KEY_ARTISTS, self._plex_client.get_artists),
            ("genres", _KEY_GENRES, self._plex_client.get_genres),
        ]:
            try:
                items = fetch_fn()
                self._write(cache_key, items)
                summary[category_name] = "ok"
            except Exception:
                summary[category_name] = "error"

        # Refresh all cached album lists
        for album_key in self._all_album_keys():
            artist_key = album_key[len("albums:"):]
            try:
                items = self._plex_client.get_albums_for_artist(artist_key)
                self._write(album_key, items)
            except Exception:
                pass  # Individual album failures don't affect summary

        return summary
