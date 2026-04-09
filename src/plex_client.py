"""Plex API client for hello-operator.

PlexClient     — concrete implementation using the Plex HTTP API.
MockPlexClient — configurable mock for unit tests; records all calls.

PlexClient raises exceptions on API failures; callers decide whether to log.
"""

import requests
from typing import Optional

from src.interfaces import MediaItem, PlaybackState, PlexClientInterface


class PlexClient(PlexClientInterface):
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
                plex_key=item["ratingKey"],
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
                    plex_key=item["ratingKey"],
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
                genres.append(MediaItem(
                    plex_key=item.get("key", item.get("title", "")),
                    name=item["title"],
                    media_type="genre",
                ))
        return genres

    def get_albums_for_artist(self, artist_key: str) -> list:
        data = self._get(f"/library/metadata/{artist_key}/children")
        items = data.get("MediaContainer", {}).get("Metadata", []) or []
        return [
            MediaItem(
                plex_key=item["ratingKey"],
                name=item["title"],
                media_type="album",
            )
            for item in items
        ]

    def play(self, plex_key: str) -> None:
        # Use Plex playback API on the server
        params = {"key": plex_key, "commandID": self._next_command_id()}
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
            plex_key=session.get("ratingKey", ""),
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


class MockPlexClient(PlexClientInterface):
    """Configurable mock for unit tests; records all calls."""

    def __init__(self) -> None:
        self.calls: list = []
        self._playlists: list = []
        self._artists: list = []
        self._genres: list = []
        self._albums: dict = {}  # artist_key -> list
        self._now_playing: PlaybackState = PlaybackState(item=None, is_paused=False)
        self._queue_position: tuple = (0, 0)

    # -- Configuration methods (test-only) ------------------------------------

    def set_playlists(self, playlists: list) -> None:
        self._playlists = playlists

    def set_artists(self, artists: list) -> None:
        self._artists = artists

    def set_genres(self, genres: list) -> None:
        self._genres = genres

    def set_albums_for_artist(self, artist_key: str, albums: list) -> None:
        self._albums[artist_key] = albums

    def set_now_playing(self, state: PlaybackState) -> None:
        self._now_playing = state

    def set_queue_position(self, current: int, total: int) -> None:
        self._queue_position = (current, total)

    # -- PlexClientInterface --------------------------------------------------

    def get_playlists(self) -> list:
        self.calls.append(('get_playlists',))
        return list(self._playlists)

    def get_artists(self) -> list:
        self.calls.append(('get_artists',))
        return list(self._artists)

    def get_genres(self) -> list:
        self.calls.append(('get_genres',))
        return list(self._genres)

    def get_albums_for_artist(self, artist_key: str) -> list:
        self.calls.append(('get_albums_for_artist', artist_key))
        return list(self._albums.get(artist_key, []))

    def play(self, plex_key: str) -> None:
        self.calls.append(('play', plex_key))

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
