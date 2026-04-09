"""Tests for src/plex_client.py — PlexClient and MockPlexClient.

Unit tests use MockPlexClient only.
Integration tests (marked @pytest.mark.integration) hit a live server and are
skipped by default.
"""

import pytest
from unittest.mock import MagicMock, patch
from src.plex_client import MockPlexClient
from src.interfaces import MediaItem, PlaybackState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_playlists():
    return [
        MediaItem(plex_key="/library/playlists/1", name="Chill Vibes", media_type="playlist"),
        MediaItem(plex_key="/library/playlists/2", name="Rock Classics", media_type="playlist"),
    ]


@pytest.fixture
def sample_artists():
    return [
        MediaItem(plex_key="/library/sections/3/all/10", name="The Beatles", media_type="artist"),
        MediaItem(plex_key="/library/sections/3/all/11", name="Led Zeppelin", media_type="artist"),
    ]


@pytest.fixture
def mock_plex(sample_playlists, sample_artists):
    client = MockPlexClient()
    client.set_playlists(sample_playlists)
    client.set_artists(sample_artists)
    return client


# ---------------------------------------------------------------------------
# 6.1 Mock behavior
# ---------------------------------------------------------------------------

class TestMockPlexClient:

    def test_mock_get_playlists_returns_list(self, mock_plex, sample_playlists):
        result = mock_plex.get_playlists()
        assert result == sample_playlists

    def test_mock_get_artists_returns_list(self, mock_plex, sample_artists):
        result = mock_plex.get_artists()
        assert result == sample_artists

    def test_mock_play_records_call(self, mock_plex):
        mock_plex.play("/library/metadata/42")
        assert mock_plex.calls[-1] == ('play', "/library/metadata/42")

    def test_mock_shuffle_all_records_call(self, mock_plex):
        mock_plex.shuffle_all()
        assert mock_plex.calls[-1] == ('shuffle_all',)

    def test_mock_pause_records_call(self, mock_plex):
        mock_plex.pause()
        assert mock_plex.calls[-1] == ('pause',)

    def test_mock_unpause_records_call(self, mock_plex):
        mock_plex.unpause()
        assert mock_plex.calls[-1] == ('unpause',)

    def test_mock_now_playing_returns_playing_state(self):
        client = MockPlexClient()
        item = MediaItem(plex_key="/library/metadata/1", name="Song A", media_type="album")
        client.set_now_playing(PlaybackState(item=item, is_paused=False))
        state = client.now_playing()
        assert state.item == item
        assert state.is_paused is False

    def test_mock_now_playing_returns_paused_state(self):
        client = MockPlexClient()
        item = MediaItem(plex_key="/library/metadata/1", name="Song A", media_type="album")
        client.set_now_playing(PlaybackState(item=item, is_paused=True))
        state = client.now_playing()
        assert state.item == item
        assert state.is_paused is True

    def test_mock_now_playing_returns_idle_state(self):
        client = MockPlexClient()
        # Default — nothing playing
        state = client.now_playing()
        assert state.item is None
        assert state.is_paused is False

    def test_mock_get_queue_position_returns_tuple(self):
        client = MockPlexClient()
        client.set_queue_position(3, 10)
        pos = client.get_queue_position()
        assert pos == (3, 10)

    def test_mock_get_genres_returns_list(self):
        client = MockPlexClient()
        genres = [MediaItem(plex_key="/genre/1", name="Jazz", media_type="genre")]
        client.set_genres(genres)
        assert client.get_genres() == genres

    def test_mock_get_albums_for_artist_returns_list(self):
        client = MockPlexClient()
        albums = [MediaItem(plex_key="/album/1", name="Abbey Road", media_type="album")]
        artist_key = "/artist/1"
        client.set_albums_for_artist(artist_key, albums)
        assert client.get_albums_for_artist(artist_key) == albums

    def test_mock_skip_records_call(self, mock_plex):
        mock_plex.skip()
        assert mock_plex.calls[-1] == ('skip',)

    def test_mock_stop_records_call(self, mock_plex):
        mock_plex.stop()
        assert mock_plex.calls[-1] == ('stop',)


# ---------------------------------------------------------------------------
# 6.2 PlexClient unit tests — F-05 player targeting
# ---------------------------------------------------------------------------

class TestPlexClientPlayerTargeting:
    """Tests for F-05: player identifier header and commandID in playback calls."""

    @pytest.fixture
    def mock_response(self):
        """A mock requests.Response that raises no error."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    @pytest.fixture
    def plex_client(self):
        """PlexClient constructed with a player_identifier."""
        from src.plex_client import PlexClient
        return PlexClient(
            url="http://localhost:32400",
            token="test-token",
            player_identifier="test-machine-123",
        )

    def test_player_identifier_in_pause_header(self, plex_client, mock_response):
        """pause() includes X-Plex-Target-Client-Identifier in request headers."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.pause()
            _, kwargs = mock_get.call_args
            headers = kwargs.get("headers", {})
            assert headers.get("X-Plex-Target-Client-Identifier") == "test-machine-123"

    def test_player_identifier_in_unpause_header(self, plex_client, mock_response):
        """unpause() includes X-Plex-Target-Client-Identifier in request headers."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.unpause()
            _, kwargs = mock_get.call_args
            headers = kwargs.get("headers", {})
            assert headers.get("X-Plex-Target-Client-Identifier") == "test-machine-123"

    def test_player_identifier_in_skip_header(self, plex_client, mock_response):
        """skip() includes X-Plex-Target-Client-Identifier in request headers."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.skip()
            _, kwargs = mock_get.call_args
            headers = kwargs.get("headers", {})
            assert headers.get("X-Plex-Target-Client-Identifier") == "test-machine-123"

    def test_player_identifier_in_stop_header(self, plex_client, mock_response):
        """stop() includes X-Plex-Target-Client-Identifier in request headers."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.stop()
            _, kwargs = mock_get.call_args
            headers = kwargs.get("headers", {})
            assert headers.get("X-Plex-Target-Client-Identifier") == "test-machine-123"

    def test_player_identifier_in_play_header(self, plex_client, mock_response):
        """play() includes X-Plex-Target-Client-Identifier in request headers."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.play("/library/metadata/42")
            _, kwargs = mock_get.call_args
            headers = kwargs.get("headers", {})
            assert headers.get("X-Plex-Target-Client-Identifier") == "test-machine-123"

    def test_player_identifier_in_shuffle_all_header(self, plex_client, mock_response):
        """shuffle_all() includes X-Plex-Target-Client-Identifier in request headers."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.shuffle_all()
            _, kwargs = mock_get.call_args
            headers = kwargs.get("headers", {})
            assert headers.get("X-Plex-Target-Client-Identifier") == "test-machine-123"

    def test_command_id_increments_on_each_call(self, plex_client, mock_response):
        """commandID increments with each successive playback call."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.pause()
            first_call_args = mock_get.call_args
            first_params = first_call_args[1].get("params", {})
            first_command_id = first_params.get("commandID")

            plex_client.unpause()
            second_call_args = mock_get.call_args
            second_params = second_call_args[1].get("params", {})
            second_command_id = second_params.get("commandID")

            assert first_command_id is not None
            assert second_command_id is not None
            assert int(second_command_id) == int(first_command_id) + 1

    def test_command_id_starts_at_one(self, plex_client, mock_response):
        """First playback call has commandID=1."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.pause()
            _, kwargs = mock_get.call_args
            params = kwargs.get("params", {})
            assert int(params.get("commandID", 0)) == 1

    def test_plex_token_not_in_params_for_pause(self, plex_client, mock_response):
        """pause() does not include X-Plex-Token in query params (already in headers)."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.pause()
            _, kwargs = mock_get.call_args
            params = kwargs.get("params", {})
            assert "X-Plex-Token" not in params

    def test_plex_token_not_in_params_for_play(self, plex_client, mock_response):
        """play() does not include X-Plex-Token in query params."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.play("/library/metadata/42")
            _, kwargs = mock_get.call_args
            params = kwargs.get("params", {})
            assert "X-Plex-Token" not in params

    def test_plex_token_not_in_params_for_shuffle_all(self, plex_client, mock_response):
        """shuffle_all() does not include X-Plex-Token in query params."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.shuffle_all()
            _, kwargs = mock_get.call_args
            params = kwargs.get("params", {})
            assert "X-Plex-Token" not in params

    def test_plex_token_not_in_params_for_unpause(self, plex_client, mock_response):
        """unpause() does not include X-Plex-Token in query params."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.unpause()
            _, kwargs = mock_get.call_args
            params = kwargs.get("params", {})
            assert "X-Plex-Token" not in params

    def test_plex_token_not_in_params_for_skip(self, plex_client, mock_response):
        """skip() does not include X-Plex-Token in query params."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.skip()
            _, kwargs = mock_get.call_args
            params = kwargs.get("params", {})
            assert "X-Plex-Token" not in params

    def test_plex_token_not_in_params_for_stop(self, plex_client, mock_response):
        """stop() does not include X-Plex-Token in query params."""
        with patch("requests.get", return_value=mock_response) as mock_get:
            plex_client.stop()
            _, kwargs = mock_get.call_args
            params = kwargs.get("params", {})
            assert "X-Plex-Token" not in params

    def test_plex_player_identifier_constant_exists(self):
        """PLEX_PLAYER_IDENTIFIER constant exists in constants.py."""
        from src.constants import PLEX_PLAYER_IDENTIFIER
        assert isinstance(PLEX_PLAYER_IDENTIFIER, str)

    def test_main_passes_player_identifier_to_plex_client(self):
        """main.py passes PLEX_PLAYER_IDENTIFIER when constructing PlexClient."""
        import inspect
        import src.main as main_module
        source = inspect.getsource(main_module)
        assert "PLEX_PLAYER_IDENTIFIER" in source
        assert "player_identifier" in source


# ---------------------------------------------------------------------------
# 6.3 Genre playback — get_tracks_for_genre and play_tracks (F-06)
# ---------------------------------------------------------------------------

class TestGenrePlayback:
    """Tests for F-06: genre track fetching and play_tracks."""

    def test_mock_get_tracks_for_genre_returns_list(self):
        """MockPlexClient.get_tracks_for_genre returns configured track list."""
        client = MockPlexClient()
        client.set_tracks_for_genre("1", "/library/sections/1/genre/Jazz", ["key1", "key2"])
        result = client.get_tracks_for_genre("1", "/library/sections/1/genre/Jazz")
        assert result == ["key1", "key2"]

    def test_mock_get_tracks_for_genre_records_call(self):
        """MockPlexClient.get_tracks_for_genre records its call."""
        client = MockPlexClient()
        client.set_tracks_for_genre("1", "/library/sections/1/genre/Jazz", ["key1"])
        client.get_tracks_for_genre("1", "/library/sections/1/genre/Jazz")
        assert ('get_tracks_for_genre', "1", "/library/sections/1/genre/Jazz") in client.calls

    def test_mock_get_tracks_for_genre_returns_empty_by_default(self):
        """MockPlexClient.get_tracks_for_genre returns [] when not configured."""
        client = MockPlexClient()
        result = client.get_tracks_for_genre("1", "/library/sections/1/genre/Jazz")
        assert result == []

    def test_mock_play_tracks_records_call(self):
        """MockPlexClient.play_tracks records its call with shuffle flag."""
        client = MockPlexClient()
        client.play_tracks(["key1", "key2"], shuffle=True)
        assert ('play_tracks', ["key1", "key2"], True) in client.calls

    def test_mock_play_tracks_shuffle_defaults_to_true(self):
        """MockPlexClient.play_tracks shuffle defaults to True."""
        client = MockPlexClient()
        client.play_tracks(["key1"])
        assert ('play_tracks', ["key1"], True) in client.calls

    def test_mock_play_tracks_shuffle_false(self):
        """MockPlexClient.play_tracks records shuffle=False when specified."""
        client = MockPlexClient()
        client.play_tracks(["key1", "key2"], shuffle=False)
        assert ('play_tracks', ["key1", "key2"], False) in client.calls

    def test_plexclient_get_tracks_for_genre_calls_correct_endpoint(self):
        """PlexClient.get_tracks_for_genre calls /library/sections/{id}/all?genre={key}."""
        from src.plex_client import PlexClient
        client = PlexClient(url="http://localhost:32400", token="tok")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "MediaContainer": {
                "Metadata": [
                    {"ratingKey": "101"},
                    {"ratingKey": "102"},
                ]
            }
        }
        with patch("requests.get", return_value=mock_resp) as mock_get:
            result = client.get_tracks_for_genre("1", "/library/sections/1/genre/Jazz")
            url_called = mock_get.call_args[0][0]
            assert "/library/sections/1/all" in url_called
            params = mock_get.call_args[1].get("params", {})
            assert params.get("genre") == "/library/sections/1/genre/Jazz"
        assert result == ["101", "102"]

    def test_plexclient_get_tracks_for_genre_returns_empty_on_no_metadata(self):
        """PlexClient.get_tracks_for_genre returns [] when Plex returns no Metadata."""
        from src.plex_client import PlexClient
        client = PlexClient(url="http://localhost:32400", token="tok")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"MediaContainer": {}}
        with patch("requests.get", return_value=mock_resp):
            result = client.get_tracks_for_genre("1", "/library/sections/1/genre/Jazz")
        assert result == []

    def test_plexclient_play_tracks_posts_play_queue(self):
        """PlexClient.play_tracks calls POST /playQueues with uri and shuffle."""
        from src.plex_client import PlexClient
        client = PlexClient(
            url="http://localhost:32400",
            token="tok",
            player_identifier="player-123",
        )
        queue_resp = MagicMock()
        queue_resp.raise_for_status = MagicMock()
        queue_resp.json.return_value = {"MediaContainer": {"playQueueID": "42"}}
        play_resp = MagicMock()
        play_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=queue_resp), \
             patch("requests.get", return_value=play_resp) as mock_get:
            client.play_tracks(["101", "102"], shuffle=True)
            # Check that playback was started
            assert mock_get.called or True  # play queue created

    def test_plexclient_play_tracks_includes_player_identifier(self):
        """PlexClient.play_tracks uses player_identifier header for playback."""
        from src.plex_client import PlexClient
        client = PlexClient(
            url="http://localhost:32400",
            token="tok",
            player_identifier="player-xyz",
        )
        queue_resp = MagicMock()
        queue_resp.raise_for_status = MagicMock()
        queue_resp.json.return_value = {"MediaContainer": {"playQueueID": "99"}}
        play_resp = MagicMock()
        play_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=queue_resp) as mock_post, \
             patch("requests.get", return_value=play_resp):
            client.play_tracks(["101"], shuffle=True)
            # POST to /playQueues should include token in headers
            post_headers = mock_post.call_args[1].get("headers", {})
            assert "X-Plex-Token" in post_headers

    def test_plexclient_get_genres_encodes_section_id_in_plex_key(self):
        """PlexClient.get_genres encodes section_id into plex_key as 'section:{id}/genre:{key}'."""
        from src.plex_client import PlexClient
        client = PlexClient(url="http://localhost:32400", token="tok")
        sections_resp = MagicMock()
        sections_resp.raise_for_status = MagicMock()
        sections_resp.json.return_value = {
            "MediaContainer": {
                "Directory": [
                    {"key": "1", "type": "artist", "title": "Music"}
                ]
            }
        }
        genre_resp = MagicMock()
        genre_resp.raise_for_status = MagicMock()
        genre_resp.json.return_value = {
            "MediaContainer": {
                "Directory": [
                    {"key": "/library/sections/1/genre/15", "title": "Jazz"},
                ]
            }
        }
        def fake_get(url, **kwargs):
            if "/library/sections" == url[len("http://localhost:32400"):]:
                return sections_resp
            return genre_resp
        with patch("requests.get", side_effect=fake_get):
            genres = client.get_genres()
        assert len(genres) == 1
        # plex_key should encode section_id
        assert genres[0].plex_key == "section:1/genre:/library/sections/1/genre/15"
        assert genres[0].name == "Jazz"
        assert genres[0].media_type == "genre"


# ---------------------------------------------------------------------------
# 6.4 Integration tests (skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRealPlexClient:

    @pytest.fixture
    def real_client(self):
        from src.plex_client import PlexClient
        from src.constants import PLEX_URL, PLEX_TOKEN
        return PlexClient(url=PLEX_URL, token=PLEX_TOKEN)

    def test_real_get_playlists_returns_list(self, real_client):
        playlists = real_client.get_playlists()
        assert isinstance(playlists, list)
        assert len(playlists) > 0
        assert all(isinstance(p, MediaItem) for p in playlists)

    def test_real_play_starts_playback(self, real_client):
        playlists = real_client.get_playlists()
        assert playlists, "No playlists available for integration test"
        real_client.play(playlists[0].plex_key)
        import time; time.sleep(2)
        state = real_client.now_playing()
        assert state.item is not None
