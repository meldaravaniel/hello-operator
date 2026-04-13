"""Plex API client for hello-operator.

PlexClient     — concrete implementation using the Plex HTTP API.
MockMediaClient — configurable mock for unit tests; records all calls.

PlexClient raises exceptions on API failures; callers decide whether to log.
"""

import requests
from typing import Optional

from src.interfaces import MediaItem, PlaybackState, MediaClientInterface


class PlexClient(MediaClientInterface):
    """Concrete Plex API client using requests + Plex HTTP API."""

    def __init__(self, url: str, token: str, player_identifier: str = "") -> None:
        self._url = url.rstrip('/')
        self._token = token
        self._player_identifier = player_identifier
        self._command_id = 0
        self._headers = {
            "X-Plex-Token": token,
            "Accept": "application/json",
        }

    def _playback_headers(self) -> dict:
        """Return headers for playback commands, including player targeting."""
        headers = dict(self._headers)
        if self._player_identifier:
            headers["X-Plex-Target-Client-Identifier"] = self._player_identifier
        return headers

    def _next_command_id(self) -> int:
        """Increment and return the next commandID for playback commands."""
        self._command_id += 1
        return self._command_id

    def _get(self, path: str) -> dict:
        resp = requests.get(f"{self._url}{path}", headers=self._headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _get_xml(self, path: str):
        headers = dict(self._headers)
        headers["Accept"] = "application/xml"
        resp = requests.get(f"{self._url}{path}", headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.text

    def get_playlists(self) -> list:
        data = self._get("/playlists")
        items = data.get("MediaContainer", {}).get("Metadata", []) or []
        return [
            MediaItem(
                media_key=item["ratingKey"],
                name=item["title"],
                media_type="playlist",
            )
            for item in items
        ]

    def get_artists(self) -> list:
        data = self._get("/library/sections")
        sections = data.get("MediaContainer", {}).get("Directory", []) or []
        music_sections = [s for s in sections if s.get("type") == "artist"]
        artists = []
        for section in music_sections:
            section_id = section["key"]
            section_data = self._get(f"/library/sections/{section_id}/all")
            for item in section_data.get("MediaContainer", {}).get("Metadata", []) or []:
                artists.append(MediaItem(
                    media_key=item["ratingKey"],
                    name=item["title"],
                    media_type="artist",
                ))
        return artists

    def get_genres(self) -> list:
        data = self._get("/library/sections")
        sections = data.get("MediaContainer", {}).get("Directory", []) or []
        music_sections = [s for s in sections if s.get("type") == "artist"]
        genres = []
        for section in music_sections:
            section_id = section["key"]
            genre_data = self._get(f"/library/sections/{section_id}/genre")
            for item in genre_data.get("MediaContainer", {}).get("Directory", []) or []:
                genre_key = item.get("key", item.get("title", ""))
                genres.append(MediaItem(
                    media_key=f"section:{section_id}/genre:{genre_key}",
                    name=item["title"],
                    media_type="genre",
                ))
        return genres

    def get_albums_for_artist(self, artist_media_key: str) -> list:
        data = self._get(f"/library/metadata/{artist_media_key}/children")
        items = data.get("MediaContainer", {}).get("Metadata", []) or []
        return [
            MediaItem(
                media_key=item["ratingKey"],
                name=item["title"],
                media_type="album",
            )
            for item in items
        ]

    def play(self, media_key: str) -> None:
        params = {"key": media_key, "commandID": self._next_command_id()}
        resp = requests.get(
            f"{self._url}/player/playback/playMedia",
            params=params,
            headers=self._playback_headers(),
            timeout=10,
        )
        resp.raise_for_status()

    def shuffle_all(self) -> None:
        params = {"shuffle": 1, "commandID": self._next_command_id()}
        resp = requests.get(
            f"{self._url}/player/playback/playAll",
            params=params,
            headers=self._playback_headers(),
            timeout=10,
        )
        resp.raise_for_status()

    def pause(self) -> None:
        params = {"commandID": self._next_command_id()}
        resp = requests.get(
            f"{self._url}/player/playback/pause",
            params=params,
            headers=self._playback_headers(),
            timeout=10,
        )
        resp.raise_for_status()

    def unpause(self) -> None:
        params = {"commandID": self._next_command_id()}
        resp = requests.get(
            f"{self._url}/player/playback/play",
            params=params,
            headers=self._playback_headers(),
            timeout=10,
        )
        resp.raise_for_status()

    def skip(self) -> None:
        params = {"commandID": self._next_command_id()}
        resp = requests.get(
            f"{self._url}/player/playback/skipNext",
            params=params,
            headers=self._playback_headers(),
            timeout=10,
        )
        resp.raise_for_status()

    def stop(self) -> None:
        params = {"commandID": self._next_command_id()}
        resp = requests.get(
            f"{self._url}/player/playback/stop",
            params=params,
            headers=self._playback_headers(),
            timeout=10,
        )
        resp.raise_for_status()

    def now_playing(self) -> PlaybackState:
        data = self._get("/status/sessions")
        sessions = data.get("MediaContainer", {}).get("Metadata", []) or []
        if not sessions:
            return PlaybackState(item=None, is_paused=False)
        session = sessions[0]
        item = MediaItem(
            media_key=session.get("ratingKey", ""),
            name=session.get("title", ""),
            media_type=session.get("type", ""),
        )
        is_paused = session.get("Player", {}).get("state", "") == "paused"
        return PlaybackState(item=item, is_paused=is_paused)

    def get_queue_position(self) -> tuple:
        data = self._get("/playQueues")
        container = data.get("MediaContainer", {})
        current = container.get("playQueueSelectedItemOffset", 0) + 1
        total = container.get("size", 0)
        return (current, total)

    def get_tracks_for_genre(self, genre_media_key: str) -> list:
        """Return list of track ratingKey values for a genre.

        genre_media_key format: "section:{section_id}/genre:{genre_key}"
        """
        section_part, genre_key = genre_media_key.split("/genre:", 1)
        section_id = section_part.split("section:", 1)[1]
        params = {"genre": genre_key}
        resp = requests.get(
            f"{self._url}/library/sections/{section_id}/all",
            params=params,
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("MediaContainer", {}).get("Metadata", []) or []
        return [item["ratingKey"] for item in items]

    def play_tracks(self, track_keys: list, shuffle: bool = True) -> None:
        """Create a Plex play queue from track keys and start playback."""
        uri = "library://plex/directory//library/metadata/" + ",".join(str(k) for k in track_keys)
        post_params = {
            "uri": uri,
            "shuffle": 1 if shuffle else 0,
            "commandID": self._next_command_id(),
        }
        resp = requests.post(
            f"{self._url}/playQueues",
            params=post_params,
            headers=self._playback_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        queue_data = resp.json()
        queue_id = queue_data.get("MediaContainer", {}).get("playQueueID", "")
        play_params = {
            "playQueueID": queue_id,
            "commandID": self._next_command_id(),
        }
        play_resp = requests.get(
            f"{self._url}/player/playback/playMedia",
            params=play_params,
            headers=self._playback_headers(),
            timeout=10,
        )
        play_resp.raise_for_status()


class MockMediaClient(MediaClientInterface):
    """Configurable mock for unit tests; records all calls."""

    def __init__(self) -> None:
        self.calls: list = []
        self._playlists: list = []
        self._artists: list = []
        self._genres: list = []
        self._albums: dict = {}  # artist_media_key -> list
        self._now_playing: PlaybackState = PlaybackState(item=None, is_paused=False)
        self._queue_position: tuple = (0, 0)
        self._tracks_for_genre: dict = {}  # genre_media_key -> list of track keys

    # -- Configuration methods (test-only) ------------------------------------

    def set_playlists(self, playlists: list) -> None:
        self._playlists = playlists

    def set_artists(self, artists: list) -> None:
        self._artists = artists

    def set_genres(self, genres: list) -> None:
        self._genres = genres

    def set_albums_for_artist(self, artist_media_key: str, albums: list) -> None:
        self._albums[artist_media_key] = albums

    def set_tracks_for_genre(self, genre_media_key: str, tracks: list) -> None:
        self._tracks_for_genre[genre_media_key] = tracks

    def set_now_playing(self, state: PlaybackState) -> None:
        self._now_playing = state

    def set_queue_position(self, current: int, total: int) -> None:
        self._queue_position = (current, total)

    # -- MediaClientInterface --------------------------------------------------

    def get_playlists(self) -> list:
        self.calls.append(('get_playlists',))
        return list(self._playlists)

    def get_artists(self) -> list:
        self.calls.append(('get_artists',))
        return list(self._artists)

    def get_genres(self) -> list:
        self.calls.append(('get_genres',))
        return list(self._genres)

    def get_albums_for_artist(self, artist_media_key: str) -> list:
        self.calls.append(('get_albums_for_artist', artist_media_key))
        return list(self._albums.get(artist_media_key, []))

    def play(self, media_key: str) -> None:
        self.calls.append(('play', media_key))

    def shuffle_all(self) -> None:
        self.calls.append(('shuffle_all',))

    def pause(self) -> None:
        self.calls.append(('pause',))

    def unpause(self) -> None:
        self.calls.append(('unpause',))

    def skip(self) -> None:
        self.calls.append(('skip',))

    def stop(self) -> None:
        self.calls.append(('stop',))

    def now_playing(self) -> PlaybackState:
        self.calls.append(('now_playing',))
        return self._now_playing

    def get_queue_position(self) -> tuple:
        self.calls.append(('get_queue_position',))
        return self._queue_position

    def get_tracks_for_genre(self, genre_media_key: str) -> list:
        self.calls.append(('get_tracks_for_genre', genre_media_key))
        return list(self._tracks_for_genre.get(genre_media_key, []))

    def play_tracks(self, track_keys: list, shuffle: bool = True) -> None:
        self.calls.append(('play_tracks', track_keys, shuffle))


# Backward-compat alias — use MockMediaClient in new code
MockPlexClient = MockMediaClient
