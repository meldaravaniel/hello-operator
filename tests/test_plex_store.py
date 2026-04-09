"""Tests for src/plex_store.py — PlexStore local SQLite cache."""

import sqlite3

import pytest
from src.plex_store import PlexStore, _KEY_PLAYLISTS, _KEY_ARTISTS, _KEY_GENRES
from src.plex_client import MockPlexClient
from src.interfaces import MediaItem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_store_db(tmp_path):
    return str(tmp_path / "plex_cache.db")


@pytest.fixture
def playlists():
    return [
        MediaItem(plex_key="/playlists/1", name="Chill Vibes", media_type="playlist"),
        MediaItem(plex_key="/playlists/2", name="Rock Classics", media_type="playlist"),
    ]


@pytest.fixture
def artists():
    return [
        MediaItem(plex_key="/artists/10", name="The Beatles", media_type="artist"),
        MediaItem(plex_key="/artists/11", name="Led Zeppelin", media_type="artist"),
    ]


@pytest.fixture
def genres():
    return [
        MediaItem(plex_key="/genre/jazz", name="Jazz", media_type="genre"),
        MediaItem(plex_key="/genre/rock", name="Rock", media_type="genre"),
    ]


@pytest.fixture
def mock_plex(playlists, artists, genres):
    client = MockPlexClient()
    client.set_playlists(playlists)
    client.set_artists(artists)
    client.set_genres(genres)
    return client


def make_store(db_path, plex_client):
    return PlexStore(db_path=db_path, plex_client=plex_client)


# ---------------------------------------------------------------------------
# 5.1 Initialization
# ---------------------------------------------------------------------------

class TestInitialization:

    def test_store_empty_on_first_run(self, tmp_store_db, mock_plex):
        store = make_store(tmp_store_db, mock_plex)
        # Accessing internal state (not categories) for emptiness check
        assert not store.playlists_has_content
        assert not store.artists_has_content
        assert not store.genres_has_content

    def test_store_fetches_from_plex_when_empty(self, tmp_store_db, mock_plex, playlists):
        store = make_store(tmp_store_db, mock_plex)
        result = store.get_playlists()
        assert result == playlists
        # Plex was called
        assert any(c[0] == 'get_playlists' for c in mock_plex.calls)

    def test_store_uses_local_data_when_populated(self, tmp_store_db, mock_plex, playlists):
        store = make_store(tmp_store_db, mock_plex)
        store.get_playlists()  # populate
        plex_call_count_before = len([c for c in mock_plex.calls if c[0] == 'get_playlists'])
        # Second call should use local data
        result = store.get_playlists()
        plex_call_count_after = len([c for c in mock_plex.calls if c[0] == 'get_playlists'])
        assert result == playlists
        assert plex_call_count_after == plex_call_count_before

    def test_store_persists_across_instantiation(self, tmp_store_db, mock_plex, playlists):
        store1 = make_store(tmp_store_db, mock_plex)
        store1.get_playlists()

        # Re-create store with fresh mock (no data — should use DB cache)
        mock2 = MockPlexClient()
        store2 = make_store(tmp_store_db, mock2)
        result = store2.get_playlists()
        assert result == playlists
        assert not any(c[0] == 'get_playlists' for c in mock2.calls)


# ---------------------------------------------------------------------------
# 5.2 Update strategy
# ---------------------------------------------------------------------------

class TestUpdateStrategy:

    def test_store_updates_on_successful_different_response(self, tmp_store_db, mock_plex, playlists):
        store = make_store(tmp_store_db, mock_plex)
        store.get_playlists()  # populate with original

        # Change Plex response
        new_playlists = [MediaItem(plex_key="/playlists/99", name="New List", media_type="playlist")]
        mock_plex.set_playlists(new_playlists)

        # Trigger update by forcing a refresh
        store.refresh()
        result = store.get_playlists()
        assert result == new_playlists

    def test_store_no_update_on_same_response(self, tmp_store_db, mock_plex, playlists):
        store = make_store(tmp_store_db, mock_plex)
        store.get_playlists()

        # Calling refresh with same data — store should not change timestamps unnecessarily
        initial_calls = len(mock_plex.calls)
        store.refresh()
        result = store.get_playlists()
        assert result == playlists  # unchanged

    def test_store_no_update_on_plex_error(self, tmp_store_db, playlists):
        # Populate first with working mock
        mock_ok = MockPlexClient()
        mock_ok.set_playlists(playlists)
        store = make_store(tmp_store_db, mock_ok)
        store.get_playlists()

        # Now use a failing mock
        class FailingMock(MockPlexClient):
            def get_playlists(self):
                raise RuntimeError("Plex unreachable")

        store._plex_client = FailingMock()
        store.refresh()  # Should not raise; local store unchanged

        result = store.get_playlists()
        assert result == playlists

    def test_store_hasContent_true_when_list_nonempty(self, tmp_store_db, mock_plex):
        store = make_store(tmp_store_db, mock_plex)
        store.get_playlists()
        assert store.playlists_has_content is True

    def test_store_hasContent_false_when_list_empty(self, tmp_store_db):
        mock = MockPlexClient()
        mock.set_playlists([])
        store = make_store(tmp_store_db, mock)
        store.get_playlists()
        assert store.playlists_has_content is False


# ---------------------------------------------------------------------------
# 5.3 Stale data / playback failure
# ---------------------------------------------------------------------------

class TestStaleData:

    def test_store_removes_item_on_playback_not_found(self, tmp_store_db, mock_plex, playlists):
        store = make_store(tmp_store_db, mock_plex)
        store.get_playlists()

        item_to_remove = playlists[0]
        store.remove_item(item_to_remove.plex_key)

        result = store.get_playlists()
        assert not any(p.plex_key == item_to_remove.plex_key for p in result)

    def test_store_updates_hasContent_after_removal(self, tmp_store_db):
        mock = MockPlexClient()
        item = MediaItem(plex_key="/playlists/1", name="Only Playlist", media_type="playlist")
        mock.set_playlists([item])
        store = make_store(tmp_store_db, mock)
        store.get_playlists()
        assert store.playlists_has_content is True

        store.remove_item(item.plex_key)
        assert store.playlists_has_content is False


# ---------------------------------------------------------------------------
# 5.4 Albums per artist
# ---------------------------------------------------------------------------

class TestAlbumsPerArtist:

    @pytest.fixture
    def albums(self):
        return [
            MediaItem(plex_key="/albums/1", name="Abbey Road", media_type="album"),
            MediaItem(plex_key="/albums/2", name="Let It Be", media_type="album"),
        ]

    def test_store_fetches_albums_on_first_access(self, tmp_store_db, mock_plex, albums):
        artist_key = "/artists/10"
        mock_plex.set_albums_for_artist(artist_key, albums)
        store = make_store(tmp_store_db, mock_plex)

        result = store.get_albums_for_artist(artist_key)
        assert result == albums
        assert any(c == ('get_albums_for_artist', artist_key) for c in mock_plex.calls)

    def test_store_uses_cached_albums(self, tmp_store_db, mock_plex, albums):
        artist_key = "/artists/10"
        mock_plex.set_albums_for_artist(artist_key, albums)
        store = make_store(tmp_store_db, mock_plex)

        store.get_albums_for_artist(artist_key)  # populate
        calls_before = len([c for c in mock_plex.calls if c[0] == 'get_albums_for_artist'])

        result = store.get_albums_for_artist(artist_key)
        calls_after = len([c for c in mock_plex.calls if c[0] == 'get_albums_for_artist'])

        assert result == albums
        assert calls_after == calls_before

    def test_store_updates_albums_on_successful_response(self, tmp_store_db, mock_plex, albums):
        artist_key = "/artists/10"
        mock_plex.set_albums_for_artist(artist_key, albums)
        store = make_store(tmp_store_db, mock_plex)
        store.get_albums_for_artist(artist_key)

        new_albums = [MediaItem(plex_key="/albums/99", name="New Album", media_type="album")]
        mock_plex.set_albums_for_artist(artist_key, new_albums)

        store.refresh()
        result = store.get_albums_for_artist(artist_key)
        assert result == new_albums


# ---------------------------------------------------------------------------
# 5.5 Manual refresh
# ---------------------------------------------------------------------------

class TestManualRefresh:

    def test_store_refresh_fetches_all_categories(self, tmp_store_db, mock_plex):
        store = make_store(tmp_store_db, mock_plex)
        mock_plex.calls.clear()
        store.refresh()
        call_types = {c[0] for c in mock_plex.calls}
        assert 'get_playlists' in call_types
        assert 'get_artists' in call_types
        assert 'get_genres' in call_types

    def test_store_refresh_updates_on_success(self, tmp_store_db, mock_plex, playlists):
        store = make_store(tmp_store_db, mock_plex)
        store.get_playlists()

        new_playlists = [MediaItem(plex_key="/playlists/99", name="New", media_type="playlist")]
        mock_plex.set_playlists(new_playlists)
        store.refresh()

        assert store.get_playlists() == new_playlists

    def test_store_refresh_skips_failed_categories(self, tmp_store_db, playlists, artists):
        mock = MockPlexClient()
        mock.set_playlists(playlists)
        mock.set_artists(artists)
        store = make_store(tmp_store_db, mock)
        store.get_playlists()
        store.get_artists()

        # Make genres fail
        class FailingMock(MockPlexClient):
            def get_genres(self):
                raise RuntimeError("Genres unavailable")
            def get_playlists(self):
                return playlists
            def get_artists(self):
                return artists

        store._plex_client = FailingMock()
        summary = store.refresh()

        # Playlists and artists updated, genres not
        assert summary.get('playlists') == 'ok'
        assert summary.get('artists') == 'ok'
        assert summary.get('genres') == 'error'
        # Local data for playlists still intact
        assert store.get_playlists() == playlists

    def test_store_refresh_returns_summary(self, tmp_store_db, mock_plex):
        store = make_store(tmp_store_db, mock_plex)
        summary = store.refresh()
        assert isinstance(summary, dict)
        assert 'playlists' in summary
        assert 'artists' in summary
        assert 'genres' in summary


# ---------------------------------------------------------------------------
# 5.6 has_content lightweight existence check
# ---------------------------------------------------------------------------

def _write_raw(db_path: str, cache_key: str, data: str) -> None:
    """Directly write a raw data string into plex_cache, bypassing PlexStore."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS plex_cache "
        "(cache_key TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO plex_cache (cache_key, data, updated_at) VALUES (?, ?, '2024-01-01T00:00:00+00:00') "
        "ON CONFLICT(cache_key) DO UPDATE SET data=excluded.data",
        (cache_key, data),
    )
    conn.commit()
    conn.close()


class TestHasContentExistenceCheck:
    """Verify has_content uses a lightweight SQL check, not full deserialization."""

    # --- playlists ---

    def test_playlists_has_content_false_when_absent(self, tmp_store_db):
        mock = MockPlexClient()
        store = make_store(tmp_store_db, mock)
        # No data written at all
        assert store.playlists_has_content is False

    def test_playlists_has_content_false_when_empty_json(self, tmp_store_db):
        mock = MockPlexClient()
        store = make_store(tmp_store_db, mock)
        _write_raw(tmp_store_db, _KEY_PLAYLISTS, '[]')
        assert store.playlists_has_content is False

    def test_playlists_has_content_true_when_nonempty(self, tmp_store_db):
        mock = MockPlexClient()
        store = make_store(tmp_store_db, mock)
        _write_raw(
            tmp_store_db,
            _KEY_PLAYLISTS,
            '[{"plex_key": "1", "name": "A", "media_type": "playlist"}]',
        )
        assert store.playlists_has_content is True

    # --- artists ---

    def test_artists_has_content_false_when_absent(self, tmp_store_db):
        mock = MockPlexClient()
        store = make_store(tmp_store_db, mock)
        assert store.artists_has_content is False

    def test_artists_has_content_false_when_empty_json(self, tmp_store_db):
        mock = MockPlexClient()
        store = make_store(tmp_store_db, mock)
        _write_raw(tmp_store_db, _KEY_ARTISTS, '[]')
        assert store.artists_has_content is False

    def test_artists_has_content_true_when_nonempty(self, tmp_store_db):
        mock = MockPlexClient()
        store = make_store(tmp_store_db, mock)
        _write_raw(
            tmp_store_db,
            _KEY_ARTISTS,
            '[{"plex_key": "/artists/1", "name": "Beatles", "media_type": "artist"}]',
        )
        assert store.artists_has_content is True

    # --- genres ---

    def test_genres_has_content_false_when_absent(self, tmp_store_db):
        mock = MockPlexClient()
        store = make_store(tmp_store_db, mock)
        assert store.genres_has_content is False

    def test_genres_has_content_false_when_empty_json(self, tmp_store_db):
        mock = MockPlexClient()
        store = make_store(tmp_store_db, mock)
        _write_raw(tmp_store_db, _KEY_GENRES, '[]')
        assert store.genres_has_content is False

    def test_genres_has_content_true_when_nonempty(self, tmp_store_db):
        mock = MockPlexClient()
        store = make_store(tmp_store_db, mock)
        _write_raw(
            tmp_store_db,
            _KEY_GENRES,
            '[{"plex_key": "/genre/rock", "name": "Rock", "media_type": "genre"}]',
        )
        assert store.genres_has_content is True
