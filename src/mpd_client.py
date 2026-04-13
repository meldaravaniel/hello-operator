"""MPD (Music Player Daemon) client for hello-operator.

MPDClient — concrete implementation using python-mpd2 over the MPD protocol.

Media key formats used by this backend:
  playlist  → "playlist:{name}"
  artist    → "artist:{name}"
  album     → "album:{name}"
  genre     → "genre:{name}"
  track     → "track:{file_path}"

MPD is a headless daemon (no display required) controlled via a simple TCP
socket protocol. See https://mpd.readthedocs.io/en/latest/protocol.html
"""

from contextlib import contextmanager
from typing import Optional

import mpd  # python-mpd2

from src.interfaces import MediaItem, PlaybackState, MediaClientInterface

_PLAYLIST_PREFIX = "playlist:"
_ARTIST_PREFIX = "artist:"
_ALBUM_PREFIX = "album:"
_GENRE_PREFIX = "genre:"
_TRACK_PREFIX = "track:"


def _strip(prefix: str, value: str) -> str:
    return value[len(prefix):] if value.startswith(prefix) else value


class MPDClient(MediaClientInterface):
    """Concrete MPD client using python-mpd2."""

    def __init__(self, host: str = "localhost", port: int = 6600) -> None:
        self._host = host
        self._port = port

    @contextmanager
    def _connection(self):
        """Context manager that yields a connected MPDClient and disconnects on exit."""
        client = mpd.MPDClient()
        client.connect(self._host, self._port)
        try:
            yield client
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Browse
    # ------------------------------------------------------------------

    def get_playlists(self) -> list:
        with self._connection() as c:
            entries = c.listplaylists()
        return [
            MediaItem(
                media_key=f"{_PLAYLIST_PREFIX}{e['playlist']}",
                name=e["playlist"],
                media_type="playlist",
            )
            for e in entries
            if e.get("playlist")
        ]

    def get_artists(self) -> list:
        with self._connection() as c:
            names = c.list("albumartist")
        return [
            MediaItem(media_key=f"{_ARTIST_PREFIX}{name}", name=name, media_type="artist")
            for name in names
            if name
        ]

    def get_genres(self) -> list:
        with self._connection() as c:
            names = c.list("genre")
        return [
            MediaItem(media_key=f"{_GENRE_PREFIX}{name}", name=name, media_type="genre")
            for name in names
            if name
        ]

    def get_albums_for_artist(self, artist_media_key: str) -> list:
        artist_name = _strip(_ARTIST_PREFIX, artist_media_key)
        with self._connection() as c:
            names = c.list("album", "albumartist", artist_name)
        return [
            MediaItem(media_key=f"{_ALBUM_PREFIX}{name}", name=name, media_type="album")
            for name in names
            if name
        ]

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def play(self, media_key: str) -> None:
        with self._connection() as c:
            c.clear()
            if media_key.startswith(_PLAYLIST_PREFIX):
                c.load(_strip(_PLAYLIST_PREFIX, media_key))
            elif media_key.startswith(_ALBUM_PREFIX):
                c.findadd("album", _strip(_ALBUM_PREFIX, media_key))
            elif media_key.startswith(_ARTIST_PREFIX):
                c.findadd("albumartist", _strip(_ARTIST_PREFIX, media_key))
            else:
                c.add(_strip(_TRACK_PREFIX, media_key))
            c.play()

    def shuffle_all(self) -> None:
        with self._connection() as c:
            c.clear()
            c.add("/")
            c.shuffle()
            c.play()

    def pause(self) -> None:
        with self._connection() as c:
            c.pause(1)

    def unpause(self) -> None:
        with self._connection() as c:
            c.pause(0)

    def skip(self) -> None:
        with self._connection() as c:
            c.next()

    def stop(self) -> None:
        with self._connection() as c:
            c.stop()

    def now_playing(self) -> PlaybackState:
        with self._connection() as c:
            status = c.status()
            state = status.get("state", "stop")
            if state == "stop":
                return PlaybackState(item=None, is_paused=False)
            song = c.currentsong()

        if not song:
            return PlaybackState(item=None, is_paused=False)

        name = song.get("title") or song.get("file", "")
        item = MediaItem(
            media_key=f"{_TRACK_PREFIX}{song.get('file', '')}",
            name=name,
            media_type="track",
        )
        return PlaybackState(item=item, is_paused=(state == "pause"))

    def get_queue_position(self) -> tuple:
        with self._connection() as c:
            status = c.status()
        # MPD song position is 0-indexed; convert to 1-indexed to match Plex convention
        pos = int(status.get("song", 0)) + 1
        total = int(status.get("playlistlength", 0))
        return (pos, total)

    def get_tracks_for_genre(self, genre_media_key: str) -> list:
        """Return track keys for a genre.

        genre_media_key format: "genre:{name}"
        Returns a list of "track:{file_path}" strings.
        """
        genre_name = _strip(_GENRE_PREFIX, genre_media_key)
        with self._connection() as c:
            songs = c.find("genre", genre_name)
        return [f"{_TRACK_PREFIX}{s['file']}" for s in songs if s.get("file")]

    def play_tracks(self, track_keys: list, shuffle: bool = True) -> None:
        with self._connection() as c:
            c.clear()
            for key in track_keys:
                c.add(_strip(_TRACK_PREFIX, key))
            if shuffle:
                c.shuffle()
            c.play()
