"""Tests for src/mpd_client.py."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch, call

import pytest

from src.interfaces import MediaItem, PlaybackState
from src.mpd_client import (
    MPDClient, MockMediaClient,
    _strip,
    _PLAYLIST_PREFIX, _ARTIST_PREFIX, _ALBUM_PREFIX, _GENRE_PREFIX, _TRACK_PREFIX,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_conn():
    """Mock MPD connection client yielded by _connection()."""
    m = MagicMock()
    m.status.return_value = {"state": "stop", "song": "0", "playlistlength": "0"}
    m.currentsong.return_value = {}
    m.listplaylists.return_value = []
    m.list.return_value = []
    m.find.return_value = []
    return m


@pytest.fixture
def client(mock_conn):
    """MPDClient with _connection() replaced so tests never touch a real socket."""
    c = MPDClient("testhost", 7700)

    @contextmanager
    def fake_connection():
        yield mock_conn

    c._connection = fake_connection
    return c


# ---------------------------------------------------------------------------
# _strip
# ---------------------------------------------------------------------------


class TestStrip:
    def test_strips_matching_prefix(self):
        assert _strip("playlist:", "playlist:Jazz") == "Jazz"

    def test_returns_value_unchanged_when_prefix_absent(self):
        assert _strip("playlist:", "Jazz") == "Jazz"

    def test_strips_artist_prefix(self):
        assert _strip("artist:", "artist:Bach") == "Bach"

    def test_strips_album_prefix(self):
        assert _strip("album:", "album:WTC") == "WTC"

    def test_strips_genre_prefix(self):
        assert _strip("genre:", "genre:Jazz") == "Jazz"

    def test_strips_track_prefix(self):
        assert _strip("track:", "track:path/to/file.mp3") == "path/to/file.mp3"

    def test_empty_value_no_prefix(self):
        assert _strip("playlist:", "") == ""

    def test_partial_prefix_not_stripped(self):
        assert _strip("playlist:", "play:Jazz") == "play:Jazz"


# ---------------------------------------------------------------------------
# MPDClient.__init__
# ---------------------------------------------------------------------------


class TestMPDClientInit:
    def test_stores_host(self):
        with patch("src.mpd_client.mpd.MPDClient"):
            c = MPDClient("myhost", 6600)
        assert c._host == "myhost"

    def test_stores_port(self):
        with patch("src.mpd_client.mpd.MPDClient"):
            c = MPDClient("localhost", 9999)
        assert c._port == 9999

    def test_default_host_is_localhost(self):
        with patch("src.mpd_client.mpd.MPDClient"):
            c = MPDClient()
        assert c._host == "localhost"

    def test_default_port_is_6600(self):
        with patch("src.mpd_client.mpd.MPDClient"):
            c = MPDClient()
        assert c._port == 6600


# ---------------------------------------------------------------------------
# _connection
# ---------------------------------------------------------------------------


class TestConnection:
    def _make_client_with_mock(self):
        mock_c = MagicMock()
        with patch("src.mpd_client.mpd.MPDClient", return_value=mock_c):
            cl = MPDClient("myhost", 9999)
        return cl, mock_c

    def test_connects_to_stored_host_and_port(self):
        mock_c = MagicMock()
        with patch("src.mpd_client.mpd.MPDClient", return_value=mock_c):
            cl = MPDClient("myhost", 9999)
            with cl._connection():
                pass
        mock_c.connect.assert_called_once_with("myhost", 9999)

    def test_yields_the_mpd_client(self):
        mock_c = MagicMock()
        with patch("src.mpd_client.mpd.MPDClient", return_value=mock_c):
            cl = MPDClient("localhost", 6600)
            with cl._connection() as yielded:
                pass
        assert yielded is mock_c

    def test_disconnects_on_normal_exit(self):
        mock_c = MagicMock()
        with patch("src.mpd_client.mpd.MPDClient", return_value=mock_c):
            cl = MPDClient("localhost", 6600)
            with cl._connection():
                pass
        mock_c.disconnect.assert_called_once()

    def test_disconnects_even_when_body_raises(self):
        mock_c = MagicMock()
        with patch("src.mpd_client.mpd.MPDClient", return_value=mock_c):
            cl = MPDClient("localhost", 6600)
            with pytest.raises(ValueError):
                with cl._connection():
                    raise ValueError("boom")
        mock_c.disconnect.assert_called_once()

    def test_swallows_disconnect_exception(self):
        mock_c = MagicMock()
        mock_c.disconnect.side_effect = Exception("already gone")
        with patch("src.mpd_client.mpd.MPDClient", return_value=mock_c):
            cl = MPDClient("localhost", 6600)
            with cl._connection():  # must not raise
                pass


# ---------------------------------------------------------------------------
# get_playlists
# ---------------------------------------------------------------------------


class TestGetPlaylists:
    def test_returns_empty_when_no_playlists(self, client, mock_conn):
        mock_conn.listplaylists.return_value = []
        assert client.get_playlists() == []

    def test_returns_media_item_per_playlist(self, client, mock_conn):
        mock_conn.listplaylists.return_value = [{"playlist": "Jazz"}]
        result = client.get_playlists()
        assert len(result) == 1

    def test_media_key_has_playlist_prefix(self, client, mock_conn):
        mock_conn.listplaylists.return_value = [{"playlist": "Jazz"}]
        assert client.get_playlists()[0].media_key == "playlist:Jazz"

    def test_name_matches_playlist_name(self, client, mock_conn):
        mock_conn.listplaylists.return_value = [{"playlist": "Jazz"}]
        assert client.get_playlists()[0].name == "Jazz"

    def test_media_type_is_playlist(self, client, mock_conn):
        mock_conn.listplaylists.return_value = [{"playlist": "Jazz"}]
        assert client.get_playlists()[0].media_type == "playlist"

    def test_multiple_playlists(self, client, mock_conn):
        mock_conn.listplaylists.return_value = [
            {"playlist": "Jazz"}, {"playlist": "Rock"}
        ]
        result = client.get_playlists()
        assert len(result) == 2
        assert result[0].name == "Jazz"
        assert result[1].name == "Rock"

    def test_filters_entries_without_playlist_key(self, client, mock_conn):
        mock_conn.listplaylists.return_value = [
            {"playlist": "Jazz"}, {"last-modified": "2024-01-01"}
        ]
        result = client.get_playlists()
        assert len(result) == 1
        assert result[0].name == "Jazz"

    def test_filters_empty_playlist_name(self, client, mock_conn):
        mock_conn.listplaylists.return_value = [{"playlist": ""}]
        assert client.get_playlists() == []

    def test_calls_listplaylists(self, client, mock_conn):
        client.get_playlists()
        mock_conn.listplaylists.assert_called_once()


# ---------------------------------------------------------------------------
# get_artists
# ---------------------------------------------------------------------------


class TestGetArtists:
    def test_returns_empty_when_no_artists(self, client, mock_conn):
        mock_conn.list.return_value = []
        assert client.get_artists() == []

    def test_calls_list_with_albumartist(self, client, mock_conn):
        mock_conn.list.return_value = []
        client.get_artists()
        mock_conn.list.assert_called_once_with("albumartist")

    def test_media_key_has_artist_prefix(self, client, mock_conn):
        mock_conn.list.return_value = [{"albumartist": "Bach"}]
        assert client.get_artists()[0].media_key == "artist:Bach"

    def test_name_matches_artist(self, client, mock_conn):
        mock_conn.list.return_value = [{"albumartist": "Bach"}]
        assert client.get_artists()[0].name == "Bach"

    def test_media_type_is_artist(self, client, mock_conn):
        mock_conn.list.return_value = [{"albumartist": "Bach"}]
        assert client.get_artists()[0].media_type == "artist"

    def test_multiple_artists(self, client, mock_conn):
        mock_conn.list.return_value = [
            {"albumartist": "Bach"}, {"albumartist": "Mozart"}
        ]
        result = client.get_artists()
        assert len(result) == 2

    def test_filters_empty_artist_names(self, client, mock_conn):
        mock_conn.list.return_value = [
            {"albumartist": "Bach"}, {"albumartist": ""}
        ]
        result = client.get_artists()
        assert len(result) == 1
        assert result[0].name == "Bach"


# ---------------------------------------------------------------------------
# get_genres
# ---------------------------------------------------------------------------


class TestGetGenres:
    def test_returns_empty_when_no_genres(self, client, mock_conn):
        mock_conn.list.return_value = []
        assert client.get_genres() == []

    def test_calls_list_with_genre(self, client, mock_conn):
        mock_conn.list.return_value = []
        client.get_genres()
        mock_conn.list.assert_called_once_with("genre")

    def test_media_key_has_genre_prefix(self, client, mock_conn):
        mock_conn.list.return_value = ["Jazz"]
        assert client.get_genres()[0].media_key == "genre:Jazz"

    def test_name_matches_genre(self, client, mock_conn):
        mock_conn.list.return_value = ["Jazz"]
        assert client.get_genres()[0].name == "Jazz"

    def test_media_type_is_genre(self, client, mock_conn):
        mock_conn.list.return_value = ["Jazz"]
        assert client.get_genres()[0].media_type == "genre"

    def test_multiple_genres(self, client, mock_conn):
        mock_conn.list.return_value = ["Jazz", "Rock", "Classical"]
        assert len(client.get_genres()) == 3

    def test_filters_empty_genre_names(self, client, mock_conn):
        mock_conn.list.return_value = ["Jazz", "", "Rock"]
        result = client.get_genres()
        assert len(result) == 2


# ---------------------------------------------------------------------------
# get_albums_for_artist
# ---------------------------------------------------------------------------


class TestGetAlbumsForArtist:
    def test_strips_artist_prefix_before_querying(self, client, mock_conn):
        mock_conn.list.return_value = []
        client.get_albums_for_artist("artist:Bach")
        mock_conn.list.assert_called_once_with("album", "albumartist", "Bach")

    def test_passes_bare_key_unchanged(self, client, mock_conn):
        mock_conn.list.return_value = []
        client.get_albums_for_artist("Bach")
        mock_conn.list.assert_called_once_with("album", "albumartist", "Bach")

    def test_returns_empty_when_no_albums(self, client, mock_conn):
        mock_conn.list.return_value = []
        assert client.get_albums_for_artist("artist:Bach") == []

    def test_media_key_has_album_prefix(self, client, mock_conn):
        mock_conn.list.return_value = ["WTC"]
        assert client.get_albums_for_artist("artist:Bach")[0].media_key == "album:WTC"

    def test_name_matches_album(self, client, mock_conn):
        mock_conn.list.return_value = ["WTC"]
        assert client.get_albums_for_artist("artist:Bach")[0].name == "WTC"

    def test_media_type_is_album(self, client, mock_conn):
        mock_conn.list.return_value = ["WTC"]
        assert client.get_albums_for_artist("artist:Bach")[0].media_type == "album"

    def test_multiple_albums(self, client, mock_conn):
        mock_conn.list.return_value = ["WTC", "Goldberg Variations"]
        assert len(client.get_albums_for_artist("artist:Bach")) == 2

    def test_filters_empty_album_names(self, client, mock_conn):
        mock_conn.list.return_value = ["WTC", ""]
        result = client.get_albums_for_artist("artist:Bach")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# play
# ---------------------------------------------------------------------------


class TestPlay:
    def test_clears_queue_first(self, client, mock_conn):
        client.play("playlist:Jazz")
        mock_conn.clear.assert_called_once()

    def test_calls_play_last(self, client, mock_conn):
        client.play("playlist:Jazz")
        mock_conn.play.assert_called_once()

    def test_playlist_calls_load_with_stripped_name(self, client, mock_conn):
        client.play("playlist:Jazz")
        mock_conn.load.assert_called_once_with("Jazz")

    def test_album_calls_findadd_album(self, client, mock_conn):
        client.play("album:WTC")
        mock_conn.findadd.assert_called_once_with("album", "WTC")

    def test_artist_calls_findadd_albumartist(self, client, mock_conn):
        client.play("artist:Bach")
        mock_conn.findadd.assert_called_once_with("albumartist", "Bach")

    def test_track_calls_add_with_file_path(self, client, mock_conn):
        client.play("track:music/bach/wtc.mp3")
        mock_conn.add.assert_called_once_with("music/bach/wtc.mp3")

    def test_unknown_prefix_falls_through_to_add(self, client, mock_conn):
        client.play("somepath/file.mp3")
        mock_conn.add.assert_called_once()

    def test_playlist_does_not_call_findadd(self, client, mock_conn):
        client.play("playlist:Jazz")
        mock_conn.findadd.assert_not_called()

    def test_album_does_not_call_load(self, client, mock_conn):
        client.play("album:WTC")
        mock_conn.load.assert_not_called()

    def test_clear_called_before_load(self, client, mock_conn):
        call_order = []
        mock_conn.clear.side_effect = lambda: call_order.append("clear")
        mock_conn.load.side_effect = lambda _: call_order.append("load")
        client.play("playlist:Jazz")
        assert call_order == ["clear", "load"]

    def test_play_called_after_load(self, client, mock_conn):
        call_order = []
        mock_conn.load.side_effect = lambda _: call_order.append("load")
        mock_conn.play.side_effect = lambda: call_order.append("play")
        client.play("playlist:Jazz")
        assert call_order == ["load", "play"]


# ---------------------------------------------------------------------------
# shuffle_all
# ---------------------------------------------------------------------------


class TestShuffleAll:
    def test_clears_queue(self, client, mock_conn):
        client.shuffle_all()
        mock_conn.clear.assert_called_once()

    def test_adds_root(self, client, mock_conn):
        client.shuffle_all()
        mock_conn.add.assert_called_once_with("/")

    def test_shuffles(self, client, mock_conn):
        client.shuffle_all()
        mock_conn.shuffle.assert_called_once()

    def test_plays(self, client, mock_conn):
        client.shuffle_all()
        mock_conn.play.assert_called_once()

    def test_order_clear_add_shuffle_play(self, client, mock_conn):
        order = []
        mock_conn.clear.side_effect = lambda: order.append("clear")
        mock_conn.add.side_effect = lambda _: order.append("add")
        mock_conn.shuffle.side_effect = lambda: order.append("shuffle")
        mock_conn.play.side_effect = lambda: order.append("play")
        client.shuffle_all()
        assert order == ["clear", "add", "shuffle", "play"]


# ---------------------------------------------------------------------------
# pause / unpause / skip / stop
# ---------------------------------------------------------------------------


class TestPlaybackControls:
    def test_pause_sends_pause_1(self, client, mock_conn):
        client.pause()
        mock_conn.pause.assert_called_once_with(1)

    def test_unpause_sends_pause_0(self, client, mock_conn):
        client.unpause()
        mock_conn.pause.assert_called_once_with(0)

    def test_skip_calls_next(self, client, mock_conn):
        client.skip()
        mock_conn.next.assert_called_once()

    def test_stop_calls_stop(self, client, mock_conn):
        client.stop()
        mock_conn.stop.assert_called_once()


# ---------------------------------------------------------------------------
# now_playing
# ---------------------------------------------------------------------------


class TestNowPlaying:
    def test_stop_state_returns_none_item(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "stop"}
        result = client.now_playing()
        assert result.item is None

    def test_stop_state_is_not_paused(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "stop"}
        assert client.now_playing().is_paused is False

    def test_stop_state_does_not_call_currentsong(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "stop"}
        client.now_playing()
        mock_conn.currentsong.assert_not_called()

    def test_play_state_with_song_returns_item(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "play"}
        mock_conn.currentsong.return_value = {
            "file": "music/track.mp3", "title": "Fugue in D"
        }
        result = client.now_playing()
        assert result.item is not None

    def test_play_state_is_not_paused(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "play"}
        mock_conn.currentsong.return_value = {
            "file": "music/track.mp3", "title": "Fugue in D"
        }
        assert client.now_playing().is_paused is False

    def test_pause_state_is_paused(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "pause"}
        mock_conn.currentsong.return_value = {
            "file": "music/track.mp3", "title": "Fugue in D"
        }
        assert client.now_playing().is_paused is True

    def test_item_media_key_uses_track_prefix_and_file(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "play"}
        mock_conn.currentsong.return_value = {"file": "music/track.mp3", "title": "T"}
        result = client.now_playing()
        assert result.item.media_key == "track:music/track.mp3"

    def test_item_name_uses_title_when_present(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "play"}
        mock_conn.currentsong.return_value = {
            "file": "music/track.mp3", "title": "Fugue in D"
        }
        assert client.now_playing().item.name == "Fugue in D"

    def test_item_name_falls_back_to_file_when_no_title(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "play"}
        mock_conn.currentsong.return_value = {"file": "music/track.mp3"}
        assert client.now_playing().item.name == "music/track.mp3"

    def test_item_media_type_is_track(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "play"}
        mock_conn.currentsong.return_value = {"file": "f.mp3", "title": "T"}
        assert client.now_playing().item.media_type == "track"

    def test_empty_song_returns_none_item(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "play"}
        mock_conn.currentsong.return_value = {}
        assert client.now_playing().item is None

    def test_missing_state_defaults_to_stop(self, client, mock_conn):
        mock_conn.status.return_value = {}
        result = client.now_playing()
        assert result.item is None


# ---------------------------------------------------------------------------
# get_queue_position
# ---------------------------------------------------------------------------


class TestGetQueuePosition:
    def test_returns_tuple(self, client, mock_conn):
        result = client.get_queue_position()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_position_is_one_indexed(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "play", "song": "0", "playlistlength": "10"}
        pos, total = client.get_queue_position()
        assert pos == 1  # MPD 0-indexed → 1-indexed

    def test_position_second_track(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "play", "song": "4", "playlistlength": "10"}
        pos, total = client.get_queue_position()
        assert pos == 5

    def test_total_matches_playlistlength(self, client, mock_conn):
        mock_conn.status.return_value = {"state": "play", "song": "2", "playlistlength": "7"}
        _, total = client.get_queue_position()
        assert total == 7

    def test_missing_song_defaults_to_position_one(self, client, mock_conn):
        mock_conn.status.return_value = {"playlistlength": "5"}
        pos, _ = client.get_queue_position()
        assert pos == 1  # int("0") + 1

    def test_missing_playlistlength_defaults_to_zero(self, client, mock_conn):
        mock_conn.status.return_value = {"song": "0"}
        _, total = client.get_queue_position()
        assert total == 0


# ---------------------------------------------------------------------------
# get_tracks_for_genre
# ---------------------------------------------------------------------------


class TestGetTracksForGenre:
    def test_strips_genre_prefix_before_querying(self, client, mock_conn):
        mock_conn.find.return_value = []
        client.get_tracks_for_genre("genre:Jazz")
        mock_conn.find.assert_called_once_with("genre", "Jazz")

    def test_passes_bare_genre_name_unchanged(self, client, mock_conn):
        mock_conn.find.return_value = []
        client.get_tracks_for_genre("Jazz")
        mock_conn.find.assert_called_once_with("genre", "Jazz")

    def test_returns_empty_when_no_songs(self, client, mock_conn):
        mock_conn.find.return_value = []
        assert client.get_tracks_for_genre("genre:Jazz") == []

    def test_returns_track_keys_with_prefix(self, client, mock_conn):
        mock_conn.find.return_value = [{"file": "music/jazz/track.mp3"}]
        result = client.get_tracks_for_genre("genre:Jazz")
        assert result == ["track:music/jazz/track.mp3"]

    def test_multiple_tracks(self, client, mock_conn):
        mock_conn.find.return_value = [
            {"file": "music/a.mp3"},
            {"file": "music/b.mp3"},
        ]
        result = client.get_tracks_for_genre("genre:Jazz")
        assert result == ["track:music/a.mp3", "track:music/b.mp3"]

    def test_filters_songs_without_file_key(self, client, mock_conn):
        mock_conn.find.return_value = [
            {"file": "music/a.mp3"},
            {"title": "No file"},
        ]
        result = client.get_tracks_for_genre("genre:Jazz")
        assert result == ["track:music/a.mp3"]


# ---------------------------------------------------------------------------
# play_tracks
# ---------------------------------------------------------------------------


class TestPlayTracks:
    def test_clears_queue_first(self, client, mock_conn):
        client.play_tracks(["track:a.mp3"])
        mock_conn.clear.assert_called_once()

    def test_adds_each_track(self, client, mock_conn):
        client.play_tracks(["track:a.mp3", "track:b.mp3"])
        assert mock_conn.add.call_count == 2

    def test_adds_stripped_file_paths(self, client, mock_conn):
        client.play_tracks(["track:music/a.mp3", "track:music/b.mp3"])
        mock_conn.add.assert_any_call("music/a.mp3")
        mock_conn.add.assert_any_call("music/b.mp3")

    def test_shuffles_when_shuffle_true(self, client, mock_conn):
        client.play_tracks(["track:a.mp3"], shuffle=True)
        mock_conn.shuffle.assert_called_once()

    def test_does_not_shuffle_when_shuffle_false(self, client, mock_conn):
        client.play_tracks(["track:a.mp3"], shuffle=False)
        mock_conn.shuffle.assert_not_called()

    def test_plays_after_adding(self, client, mock_conn):
        client.play_tracks(["track:a.mp3"])
        mock_conn.play.assert_called_once()

    def test_order_clear_add_shuffle_play(self, client, mock_conn):
        order = []
        mock_conn.clear.side_effect = lambda: order.append("clear")
        mock_conn.add.side_effect = lambda _: order.append("add")
        mock_conn.shuffle.side_effect = lambda: order.append("shuffle")
        mock_conn.play.side_effect = lambda: order.append("play")
        client.play_tracks(["track:a.mp3"], shuffle=True)
        assert order == ["clear", "add", "shuffle", "play"]

    def test_empty_track_list(self, client, mock_conn):
        client.play_tracks([])
        mock_conn.add.assert_not_called()
        mock_conn.play.assert_called_once()


# ---------------------------------------------------------------------------
# MockMediaClient
# ---------------------------------------------------------------------------


class TestMockMediaClientInit:
    def test_calls_starts_empty(self):
        m = MockMediaClient()
        assert m.calls == []

    def test_playlists_starts_empty(self):
        m = MockMediaClient()
        assert m._playlists == []

    def test_artists_starts_empty(self):
        m = MockMediaClient()
        assert m._artists == []

    def test_genres_starts_empty(self):
        m = MockMediaClient()
        assert m._genres == []

    def test_albums_starts_empty(self):
        m = MockMediaClient()
        assert m._albums == {}

    def test_now_playing_starts_with_none_item(self):
        m = MockMediaClient()
        assert m.now_playing().item is None

    def test_queue_position_starts_at_zero_zero(self):
        m = MockMediaClient()
        assert m.get_queue_position() == (0, 0)

    def test_tracks_for_genre_starts_empty(self):
        m = MockMediaClient()
        assert m._tracks_for_genre == {}


class TestMockMediaClientSetters:
    def test_set_playlists(self):
        m = MockMediaClient()
        items = [MediaItem("pl:1", "Jazz", "playlist")]
        m.set_playlists(items)
        assert m.get_playlists() == items

    def test_set_artists(self):
        m = MockMediaClient()
        items = [MediaItem("artist:bach", "Bach", "artist")]
        m.set_artists(items)
        assert m.get_artists() == items

    def test_set_genres(self):
        m = MockMediaClient()
        items = [MediaItem("genre:Jazz", "Jazz", "genre")]
        m.set_genres(items)
        assert m.get_genres() == items

    def test_set_albums_for_artist(self):
        m = MockMediaClient()
        albums = [MediaItem("album:wtc", "WTC", "album")]
        m.set_albums_for_artist("artist:bach", albums)
        assert m.get_albums_for_artist("artist:bach") == albums

    def test_set_tracks_for_genre(self):
        m = MockMediaClient()
        tracks = ["track:a.mp3", "track:b.mp3"]
        m.set_tracks_for_genre("genre:Jazz", tracks)
        assert m.get_tracks_for_genre("genre:Jazz") == tracks

    def test_set_now_playing(self):
        m = MockMediaClient()
        item = MediaItem("track:a.mp3", "Song", "track")
        state = PlaybackState(item=item, is_paused=False)
        m.set_now_playing(state)
        assert m.now_playing().item is item

    def test_set_queue_position(self):
        m = MockMediaClient()
        m.set_queue_position(3, 10)
        assert m.get_queue_position() == (3, 10)


class TestMockMediaClientGetters:
    def test_get_playlists_records_call(self):
        m = MockMediaClient()
        m.get_playlists()
        assert ('get_playlists',) in m.calls

    def test_get_artists_records_call(self):
        m = MockMediaClient()
        m.get_artists()
        assert ('get_artists',) in m.calls

    def test_get_genres_records_call(self):
        m = MockMediaClient()
        m.get_genres()
        assert ('get_genres',) in m.calls

    def test_get_albums_for_artist_records_call_with_key(self):
        m = MockMediaClient()
        m.get_albums_for_artist("artist:bach")
        assert ('get_albums_for_artist', 'artist:bach') in m.calls

    def test_get_albums_for_unknown_artist_returns_empty(self):
        m = MockMediaClient()
        assert m.get_albums_for_artist("artist:nobody") == []

    def test_get_tracks_for_genre_records_call(self):
        m = MockMediaClient()
        m.get_tracks_for_genre("genre:Jazz")
        assert ('get_tracks_for_genre', 'genre:Jazz') in m.calls

    def test_get_tracks_for_unknown_genre_returns_empty(self):
        m = MockMediaClient()
        assert m.get_tracks_for_genre("genre:Unknown") == []

    def test_now_playing_records_call(self):
        m = MockMediaClient()
        m.now_playing()
        assert ('now_playing',) in m.calls

    def test_get_queue_position_records_call(self):
        m = MockMediaClient()
        m.get_queue_position()
        assert ('get_queue_position',) in m.calls

    def test_get_playlists_returns_copy(self):
        m = MockMediaClient()
        items = [MediaItem("pl:1", "Jazz", "playlist")]
        m.set_playlists(items)
        result = m.get_playlists()
        result.append(MediaItem("pl:2", "extra", "playlist"))
        assert len(m.get_playlists()) == 1


class TestMockMediaClientMutators:
    def test_play_records_call(self):
        m = MockMediaClient()
        m.play("pl:jazz")
        assert ('play', 'pl:jazz') in m.calls

    def test_shuffle_all_records_call(self):
        m = MockMediaClient()
        m.shuffle_all()
        assert ('shuffle_all',) in m.calls

    def test_pause_records_call(self):
        m = MockMediaClient()
        m.pause()
        assert ('pause',) in m.calls

    def test_unpause_records_call(self):
        m = MockMediaClient()
        m.unpause()
        assert ('unpause',) in m.calls

    def test_skip_records_call(self):
        m = MockMediaClient()
        m.skip()
        assert ('skip',) in m.calls

    def test_stop_records_call(self):
        m = MockMediaClient()
        m.stop()
        assert ('stop',) in m.calls

    def test_play_tracks_records_call_with_args(self):
        m = MockMediaClient()
        m.play_tracks(["track:a.mp3"], shuffle=True)
        assert ('play_tracks', ["track:a.mp3"], True) in m.calls

    def test_play_tracks_records_shuffle_false(self):
        m = MockMediaClient()
        m.play_tracks(["track:a.mp3"], shuffle=False)
        assert ('play_tracks', ["track:a.mp3"], False) in m.calls
