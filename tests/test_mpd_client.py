"""Tests for src/mpd_client.py — MPDClient concrete implementation.

All tests use a mocked mpd.MPDClient (python-mpd2) so no running MPD daemon
is required. The `mpd` module is pre-mocked in conftest.py.
"""

import sys
import pytest
from unittest.mock import MagicMock, patch, call

from src.mpd_client import MPDClient, _PLAYLIST_PREFIX, _ARTIST_PREFIX, _ALBUM_PREFIX, _GENRE_PREFIX, _TRACK_PREFIX
from src.interfaces import MediaItem, PlaybackState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client() -> MPDClient:
    return MPDClient(host="localhost", port=6600)


def _mpd_conn_mock(**kwargs) -> MagicMock:
    """Return a MagicMock that simulates a connected mpd.MPDClient instance.

    Extra kwargs are set as attributes on the mock (e.g. status=...).
    """
    conn = MagicMock()
    for k, v in kwargs.items():
        getattr(conn, k).return_value = v
    return conn


def _patch_mpd(conn_mock: MagicMock):
    """Context manager: patch mpd.MPDClient so _connection() yields conn_mock."""
    mpd_mod = sys.modules['mpd']
    mpd_mod.MPDClient.return_value = conn_mock
    return conn_mock


# ---------------------------------------------------------------------------
# 5A.1 Browse — get_playlists
# ---------------------------------------------------------------------------

class TestGetPlaylists:

    def test_returns_playlist_media_items(self):
        """get_playlists() converts listplaylists() entries to MediaItems."""
        conn = _mpd_conn_mock()
        conn.listplaylists.return_value = [
            {"playlist": "Chill Vibes", "last-modified": "2024-01-01"},
            {"playlist": "Rock Classics", "last-modified": "2024-01-01"},
        ]
        _patch_mpd(conn)
        client = _make_client()
        result = client.get_playlists()
        assert len(result) == 2
        assert result[0].media_key == "playlist:Chill Vibes"
        assert result[0].name == "Chill Vibes"
        assert result[0].media_type == "playlist"
        assert result[1].media_key == "playlist:Rock Classics"

    def test_empty_playlists(self):
        """get_playlists() returns [] when MPD has no playlists."""
        conn = _mpd_conn_mock()
        conn.listplaylists.return_value = []
        _patch_mpd(conn)
        result = _make_client().get_playlists()
        assert result == []

    def test_skips_entries_without_playlist_key(self):
        """get_playlists() skips entries with empty/missing playlist name."""
        conn = _mpd_conn_mock()
        conn.listplaylists.return_value = [
            {"playlist": "Good Playlist"},
            {"playlist": ""},
            {},
        ]
        _patch_mpd(conn)
        result = _make_client().get_playlists()
        assert len(result) == 1
        assert result[0].name == "Good Playlist"

    def test_connects_and_disconnects(self):
        """get_playlists() calls connect() and disconnect()."""
        conn = _mpd_conn_mock()
        conn.listplaylists.return_value = []
        _patch_mpd(conn)
        _make_client().get_playlists()
        conn.connect.assert_called_once_with("localhost", 6600)
        conn.disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# 5A.2 Browse — get_artists
# ---------------------------------------------------------------------------

class TestGetArtists:

    def test_returns_artist_media_items(self):
        """get_artists() converts albumartist list to MediaItems with artist: prefix."""
        conn = _mpd_conn_mock()
        conn.list.return_value = ["The Beatles", "Led Zeppelin"]
        _patch_mpd(conn)
        result = _make_client().get_artists()
        assert len(result) == 2
        assert result[0].media_key == "artist:The Beatles"
        assert result[0].name == "The Beatles"
        assert result[0].media_type == "artist"

    def test_skips_empty_artist_names(self):
        """get_artists() skips empty strings from MPD."""
        conn = _mpd_conn_mock()
        conn.list.return_value = ["Artist A", "", "Artist B"]
        _patch_mpd(conn)
        result = _make_client().get_artists()
        assert len(result) == 2

    def test_calls_list_albumartist(self):
        """get_artists() calls c.list('albumartist')."""
        conn = _mpd_conn_mock()
        conn.list.return_value = []
        _patch_mpd(conn)
        _make_client().get_artists()
        conn.list.assert_called_once_with("albumartist")


# ---------------------------------------------------------------------------
# 5A.3 Browse — get_genres
# ---------------------------------------------------------------------------

class TestGetGenres:

    def test_returns_genre_media_items(self):
        """get_genres() converts genre list to MediaItems with genre: prefix."""
        conn = _mpd_conn_mock()
        conn.list.return_value = ["Jazz", "Rock", "Classical"]
        _patch_mpd(conn)
        result = _make_client().get_genres()
        assert len(result) == 3
        assert result[0].media_key == "genre:Jazz"
        assert result[0].name == "Jazz"
        assert result[0].media_type == "genre"

    def test_skips_empty_genre_names(self):
        """get_genres() skips empty strings."""
        conn = _mpd_conn_mock()
        conn.list.return_value = ["Jazz", ""]
        _patch_mpd(conn)
        result = _make_client().get_genres()
        assert len(result) == 1

    def test_calls_list_genre(self):
        """get_genres() calls c.list('genre')."""
        conn = _mpd_conn_mock()
        conn.list.return_value = []
        _patch_mpd(conn)
        _make_client().get_genres()
        conn.list.assert_called_once_with("genre")


# ---------------------------------------------------------------------------
# 5A.4 Browse — get_albums_for_artist
# ---------------------------------------------------------------------------

class TestGetAlbumsForArtist:

    def test_returns_album_media_items(self):
        """get_albums_for_artist() converts album list to MediaItems."""
        conn = _mpd_conn_mock()
        conn.list.return_value = ["Abbey Road", "Let It Be"]
        _patch_mpd(conn)
        result = _make_client().get_albums_for_artist("artist:The Beatles")
        assert len(result) == 2
        assert result[0].media_key == "album:Abbey Road"
        assert result[0].name == "Abbey Road"
        assert result[0].media_type == "album"

    def test_strips_artist_prefix_before_querying(self):
        """get_albums_for_artist() strips 'artist:' prefix when calling MPD."""
        conn = _mpd_conn_mock()
        conn.list.return_value = []
        _patch_mpd(conn)
        _make_client().get_albums_for_artist("artist:The Beatles")
        conn.list.assert_called_once_with("album", "albumartist", "The Beatles")

    def test_handles_raw_artist_name(self):
        """get_albums_for_artist() works if prefix is already absent."""
        conn = _mpd_conn_mock()
        conn.list.return_value = []
        _patch_mpd(conn)
        _make_client().get_albums_for_artist("The Beatles")
        conn.list.assert_called_once_with("album", "albumartist", "The Beatles")


# ---------------------------------------------------------------------------
# 5A.5 Playback — play
# ---------------------------------------------------------------------------

class TestPlay:

    def test_play_playlist(self):
        """play('playlist:Name') calls clear() then load(name) then play()."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().play("playlist:Chill Vibes")
        conn.clear.assert_called_once()
        conn.load.assert_called_once_with("Chill Vibes")
        conn.play.assert_called_once()

    def test_play_album(self):
        """play('album:Name') calls clear() then findadd('album', name) then play()."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().play("album:Abbey Road")
        conn.clear.assert_called_once()
        conn.findadd.assert_called_once_with("album", "Abbey Road")
        conn.play.assert_called_once()

    def test_play_artist(self):
        """play('artist:Name') calls clear() then findadd('albumartist', name) then play()."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().play("artist:The Beatles")
        conn.clear.assert_called_once()
        conn.findadd.assert_called_once_with("albumartist", "The Beatles")
        conn.play.assert_called_once()

    def test_play_track(self):
        """play('track:path/to/song.mp3') calls clear() then add(path) then play()."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().play("track:path/to/song.mp3")
        conn.clear.assert_called_once()
        conn.add.assert_called_once_with("path/to/song.mp3")
        conn.play.assert_called_once()


# ---------------------------------------------------------------------------
# 5A.6 Playback — shuffle_all
# ---------------------------------------------------------------------------

class TestShuffleAll:

    def test_shuffle_all_clears_and_plays(self):
        """shuffle_all() calls clear(), add('/'), shuffle(), play() in order."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().shuffle_all()
        conn.clear.assert_called_once()
        conn.add.assert_called_once_with("/")
        conn.shuffle.assert_called_once()
        conn.play.assert_called_once()


# ---------------------------------------------------------------------------
# 5A.7 Playback — pause / unpause / skip / stop
# ---------------------------------------------------------------------------

class TestPlaybackControls:

    def test_pause_calls_pause_1(self):
        """pause() calls c.pause(1)."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().pause()
        conn.pause.assert_called_once_with(1)

    def test_unpause_calls_pause_0(self):
        """unpause() calls c.pause(0)."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().unpause()
        conn.pause.assert_called_once_with(0)

    def test_skip_calls_next(self):
        """skip() calls c.next()."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().skip()
        conn.next.assert_called_once()

    def test_stop_calls_stop(self):
        """stop() calls c.stop()."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().stop()
        conn.stop.assert_called_once()


# ---------------------------------------------------------------------------
# 5A.8 now_playing
# ---------------------------------------------------------------------------

class TestNowPlaying:

    def test_now_playing_stopped_returns_none(self):
        """now_playing() returns PlaybackState(None, False) when MPD state is 'stop'."""
        conn = _mpd_conn_mock()
        conn.status.return_value = {"state": "stop"}
        _patch_mpd(conn)
        state = _make_client().now_playing()
        assert state.item is None
        assert state.is_paused is False

    def test_now_playing_playing_returns_item(self):
        """now_playing() returns the current song as a track MediaItem when playing."""
        conn = _mpd_conn_mock()
        conn.status.return_value = {"state": "play"}
        conn.currentsong.return_value = {
            "file": "music/song.mp3",
            "title": "My Song",
            "artist": "Some Artist",
        }
        _patch_mpd(conn)
        state = _make_client().now_playing()
        assert state.item is not None
        assert state.item.media_key == "track:music/song.mp3"
        assert state.item.name == "My Song"
        assert state.item.media_type == "track"
        assert state.is_paused is False

    def test_now_playing_paused_returns_is_paused_true(self):
        """now_playing() returns is_paused=True when MPD state is 'pause'."""
        conn = _mpd_conn_mock()
        conn.status.return_value = {"state": "pause"}
        conn.currentsong.return_value = {
            "file": "music/song.mp3",
            "title": "My Song",
        }
        _patch_mpd(conn)
        state = _make_client().now_playing()
        assert state.is_paused is True

    def test_now_playing_no_song_returns_none(self):
        """now_playing() returns None item when currentsong() returns empty dict."""
        conn = _mpd_conn_mock()
        conn.status.return_value = {"state": "play"}
        conn.currentsong.return_value = {}
        _patch_mpd(conn)
        state = _make_client().now_playing()
        assert state.item is None

    def test_now_playing_uses_file_as_name_when_no_title(self):
        """now_playing() falls back to file path as name when title is absent."""
        conn = _mpd_conn_mock()
        conn.status.return_value = {"state": "play"}
        conn.currentsong.return_value = {"file": "music/untitled.mp3"}
        _patch_mpd(conn)
        state = _make_client().now_playing()
        assert state.item is not None
        assert state.item.name == "music/untitled.mp3"


# ---------------------------------------------------------------------------
# 5A.9 get_queue_position
# ---------------------------------------------------------------------------

class TestGetQueuePosition:

    def test_returns_1_indexed_position_and_total(self):
        """get_queue_position() converts 0-indexed song to 1-indexed, returns (pos, total)."""
        conn = _mpd_conn_mock()
        conn.status.return_value = {"song": "2", "playlistlength": "10"}
        _patch_mpd(conn)
        pos, total = _make_client().get_queue_position()
        assert pos == 3  # 0-indexed 2 → 1-indexed 3
        assert total == 10

    def test_defaults_when_stopped(self):
        """get_queue_position() returns (1, 0) when no song is active."""
        conn = _mpd_conn_mock()
        conn.status.return_value = {"playlistlength": "0"}
        _patch_mpd(conn)
        pos, total = _make_client().get_queue_position()
        assert pos == 1
        assert total == 0


# ---------------------------------------------------------------------------
# 5A.10 get_tracks_for_genre
# ---------------------------------------------------------------------------

class TestGetTracksForGenre:

    def test_returns_track_keys(self):
        """get_tracks_for_genre() returns list of 'track:{file}' strings."""
        conn = _mpd_conn_mock()
        conn.find.return_value = [
            {"file": "music/jazz1.mp3"},
            {"file": "music/jazz2.mp3"},
        ]
        _patch_mpd(conn)
        result = _make_client().get_tracks_for_genre("genre:Jazz")
        assert result == ["track:music/jazz1.mp3", "track:music/jazz2.mp3"]

    def test_strips_genre_prefix_before_querying(self):
        """get_tracks_for_genre() strips 'genre:' prefix when calling MPD."""
        conn = _mpd_conn_mock()
        conn.find.return_value = []
        _patch_mpd(conn)
        _make_client().get_tracks_for_genre("genre:Jazz")
        conn.find.assert_called_once_with("genre", "Jazz")

    def test_skips_songs_without_file(self):
        """get_tracks_for_genre() skips entries with no file path."""
        conn = _mpd_conn_mock()
        conn.find.return_value = [
            {"file": "music/track1.mp3"},
            {"title": "No File"},
            {"file": ""},
        ]
        _patch_mpd(conn)
        result = _make_client().get_tracks_for_genre("genre:Jazz")
        assert result == ["track:music/track1.mp3"]

    def test_empty_genre_returns_empty_list(self):
        """get_tracks_for_genre() returns [] when MPD finds no tracks."""
        conn = _mpd_conn_mock()
        conn.find.return_value = []
        _patch_mpd(conn)
        result = _make_client().get_tracks_for_genre("genre:Unknown")
        assert result == []


# ---------------------------------------------------------------------------
# 5A.11 play_tracks
# ---------------------------------------------------------------------------

class TestPlayTracks:

    def test_play_tracks_clears_adds_and_plays(self):
        """play_tracks() clears the queue, adds each track, then starts playing."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().play_tracks(
            ["track:music/a.mp3", "track:music/b.mp3"], shuffle=False
        )
        conn.clear.assert_called_once()
        assert conn.add.call_count == 2
        conn.add.assert_any_call("music/a.mp3")
        conn.add.assert_any_call("music/b.mp3")
        conn.play.assert_called_once()

    def test_play_tracks_shuffles_when_requested(self):
        """play_tracks(shuffle=True) calls shuffle() before play()."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().play_tracks(["track:music/a.mp3"], shuffle=True)
        conn.shuffle.assert_called_once()
        conn.play.assert_called_once()

    def test_play_tracks_no_shuffle_when_false(self):
        """play_tracks(shuffle=False) does NOT call shuffle()."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().play_tracks(["track:music/a.mp3"], shuffle=False)
        conn.shuffle.assert_not_called()

    def test_play_tracks_default_shuffle_is_true(self):
        """play_tracks() shuffles by default."""
        conn = _mpd_conn_mock()
        _patch_mpd(conn)
        _make_client().play_tracks(["track:music/a.mp3"])
        conn.shuffle.assert_called_once()


# ---------------------------------------------------------------------------
# 5A.12 Connection lifecycle
# ---------------------------------------------------------------------------

class TestConnectionLifecycle:

    def test_disconnect_called_after_success(self):
        """disconnect() is called after a successful method call."""
        conn = _mpd_conn_mock()
        conn.listplaylists.return_value = []
        _patch_mpd(conn)
        _make_client().get_playlists()
        conn.disconnect.assert_called_once()

    def test_disconnect_called_after_exception(self):
        """disconnect() is called even if the MPD call raises."""
        conn = _mpd_conn_mock()
        conn.listplaylists.side_effect = Exception("MPD error")
        _patch_mpd(conn)
        with pytest.raises(Exception, match="MPD error"):
            _make_client().get_playlists()
        conn.disconnect.assert_called_once()
