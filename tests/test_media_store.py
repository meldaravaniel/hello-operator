"""Tests for src/media_store.py."""

import json
from unittest.mock import MagicMock, call

import pytest

from src.interfaces import MediaItem
from src.media_store import (
    MediaStore, MockMediaStore,
    _now_iso, _serialize, _deserialize, _albums_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pl(name="Jazz", key="pl:1"):
    return MediaItem(media_key=key, name=name, media_type="playlist")


def _artist(name="Bach", key="artist:bach"):
    return MediaItem(media_key=key, name=name, media_type="artist")


def _genre(name="Classical", key="genre:Classical"):
    return MediaItem(media_key=key, name=name, media_type="genre")


def _album(name="WTC", key="album:wtc"):
    return MediaItem(media_key=key, name=name, media_type="album")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    m = MagicMock()
    m.get_playlists.return_value = []
    m.get_artists.return_value = []
    m.get_genres.return_value = []
    m.get_albums_for_artist.return_value = []
    return m


@pytest.fixture
def mock_error_queue():
    return MagicMock()


@pytest.fixture
def store(tmp_path, mock_client, mock_error_queue):
    return MediaStore(str(tmp_path / "media.db"), mock_client, mock_error_queue)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestNowIso:
    def test_returns_string(self):
        assert isinstance(_now_iso(), str)

    def test_contains_timezone_marker(self):
        result = _now_iso()
        assert "+" in result or "Z" in result or result.endswith("+00:00")

    def test_iso_format_parseable(self):
        from datetime import datetime
        result = _now_iso()
        # Should not raise
        datetime.fromisoformat(result)


class TestSerialize:
    def test_returns_string(self):
        assert isinstance(_serialize([_pl()]), str)

    def test_empty_list_returns_json_array(self):
        assert _serialize([]) == "[]"

    def test_single_item_has_correct_fields(self):
        data = json.loads(_serialize([_pl("Jazz", "pl:1")]))
        assert data[0] == {"media_key": "pl:1", "name": "Jazz", "media_type": "playlist"}

    def test_multiple_items_all_present(self):
        items = [_pl("Jazz", "pl:1"), _pl("Rock", "pl:2")]
        data = json.loads(_serialize(items))
        assert len(data) == 2

    def test_preserves_order(self):
        items = [_pl("Jazz", "pl:1"), _pl("Rock", "pl:2")]
        data = json.loads(_serialize(items))
        assert data[0]["name"] == "Jazz"
        assert data[1]["name"] == "Rock"


class TestDeserialize:
    def test_empty_json_array_returns_empty_list(self):
        assert _deserialize("[]") == []

    def test_single_item_returns_media_item(self):
        raw = json.dumps([{"media_key": "pl:1", "name": "Jazz", "media_type": "playlist"}])
        result = _deserialize(raw)
        assert result == [MediaItem(media_key="pl:1", name="Jazz", media_type="playlist")]

    def test_multiple_items(self):
        raw = json.dumps([
            {"media_key": "pl:1", "name": "Jazz", "media_type": "playlist"},
            {"media_key": "pl:2", "name": "Rock", "media_type": "playlist"},
        ])
        result = _deserialize(raw)
        assert len(result) == 2

    def test_roundtrip(self):
        items = [_pl("Jazz", "pl:1"), _artist("Bach", "artist:bach")]
        assert _deserialize(_serialize(items)) == items


class TestAlbumsKey:
    def test_prefixes_with_albums(self):
        assert _albums_key("artist:bach") == "albums:artist:bach"

    def test_plain_key(self):
        assert _albums_key("somekey") == "albums:somekey"


# ---------------------------------------------------------------------------
# MockMediaStore
# ---------------------------------------------------------------------------


class TestMockMediaStoreInit:
    def test_playlists_starts_empty(self):
        m = MockMediaStore()
        assert m._playlists == []

    def test_artists_starts_empty(self):
        m = MockMediaStore()
        assert m._artists == []

    def test_genres_starts_empty(self):
        m = MockMediaStore()
        assert m._genres == []

    def test_albums_starts_empty(self):
        m = MockMediaStore()
        assert m._albums == {}

    def test_calls_starts_empty(self):
        m = MockMediaStore()
        assert m.calls == []


class TestMockMediaStoreHasContent:
    def test_playlists_has_content_false_when_empty(self):
        m = MockMediaStore()
        assert m.playlists_has_content is False

    def test_artists_has_content_false_when_empty(self):
        m = MockMediaStore()
        assert m.artists_has_content is False

    def test_genres_has_content_false_when_empty(self):
        m = MockMediaStore()
        assert m.genres_has_content is False

    def test_playlists_has_content_true_when_populated(self):
        m = MockMediaStore()
        m.set_playlists([_pl()])
        assert m.playlists_has_content is True

    def test_artists_has_content_true_when_populated(self):
        m = MockMediaStore()
        m.set_artists([_artist()])
        assert m.artists_has_content is True

    def test_genres_has_content_true_when_populated(self):
        m = MockMediaStore()
        m.set_genres([_genre()])
        assert m.genres_has_content is True


class TestMockMediaStoreGetters:
    def test_get_playlists_returns_configured_items(self):
        m = MockMediaStore()
        items = [_pl("Jazz"), _pl("Rock", "pl:2")]
        m.set_playlists(items)
        assert m.get_playlists() == items

    def test_get_artists_returns_configured_items(self):
        m = MockMediaStore()
        m.set_artists([_artist("Bach")])
        assert m.get_artists() == [_artist("Bach")]

    def test_get_genres_returns_configured_items(self):
        m = MockMediaStore()
        m.set_genres([_genre("Jazz")])
        assert m.get_genres() == [_genre("Jazz")]

    def test_get_albums_for_artist_returns_configured_albums(self):
        m = MockMediaStore()
        albums = [_album("WTC"), _album("BWV", "album:bwv")]
        m.set_albums_for_artist("artist:bach", albums)
        assert m.get_albums_for_artist("artist:bach") == albums

    def test_get_albums_for_unknown_artist_returns_empty(self):
        m = MockMediaStore()
        assert m.get_albums_for_artist("artist:unknown") == []

    def test_get_playlists_records_call(self):
        m = MockMediaStore()
        m.get_playlists()
        assert ('get_playlists',) in m.calls

    def test_get_artists_records_call(self):
        m = MockMediaStore()
        m.get_artists()
        assert ('get_artists',) in m.calls

    def test_get_genres_records_call(self):
        m = MockMediaStore()
        m.get_genres()
        assert ('get_genres',) in m.calls

    def test_get_albums_for_artist_records_call_with_key(self):
        m = MockMediaStore()
        m.get_albums_for_artist("artist:bach")
        assert ('get_albums_for_artist', "artist:bach") in m.calls

    def test_get_playlists_returns_copy(self):
        m = MockMediaStore()
        items = [_pl()]
        m.set_playlists(items)
        result = m.get_playlists()
        result.append(_pl("extra", "pl:extra"))
        assert m.get_playlists() == items  # original unchanged


class TestMockMediaStoreRemoveItem:
    def test_removes_from_playlists(self):
        m = MockMediaStore()
        m.set_playlists([_pl("Jazz", "pl:1"), _pl("Rock", "pl:2")])
        m.remove_item("pl:1")
        assert m.get_playlists() == [_pl("Rock", "pl:2")]

    def test_removes_from_artists(self):
        m = MockMediaStore()
        m.set_artists([_artist("Bach", "artist:bach"), _artist("Mozart", "artist:mozart")])
        m.remove_item("artist:bach")
        assert m.get_artists() == [_artist("Mozart", "artist:mozart")]

    def test_removes_from_genres(self):
        m = MockMediaStore()
        m.set_genres([_genre("Jazz", "genre:Jazz"), _genre("Rock", "genre:Rock")])
        m.remove_item("genre:Jazz")
        assert m.get_genres() == [_genre("Rock", "genre:Rock")]

    def test_removes_from_albums(self):
        m = MockMediaStore()
        m.set_albums_for_artist("artist:bach", [_album("WTC", "album:wtc"), _album("BWV", "album:bwv")])
        m.remove_item("album:wtc")
        assert m.get_albums_for_artist("artist:bach") == [_album("BWV", "album:bwv")]

    def test_no_op_when_item_not_present(self):
        m = MockMediaStore()
        m.set_playlists([_pl()])
        m.remove_item("nonexistent")
        assert len(m.get_playlists()) == 1

    def test_records_call(self):
        m = MockMediaStore()
        m.remove_item("pl:1")
        assert ('remove_item', 'pl:1') in m.calls


class TestMockMediaStoreRefresh:
    def test_returns_configured_result(self):
        m = MockMediaStore()
        result = m.refresh()
        assert result == {'playlists': 'ok', 'artists': 'ok', 'genres': 'ok'}

    def test_returns_custom_result_when_configured(self):
        m = MockMediaStore()
        m.set_refresh_result({'playlists': 'error'})
        assert m.refresh() == {'playlists': 'error'}

    def test_records_call(self):
        m = MockMediaStore()
        m.refresh()
        assert ('refresh',) in m.calls

    def test_returns_copy_of_result(self):
        m = MockMediaStore()
        r1 = m.refresh()
        r1['playlists'] = 'modified'
        assert m.refresh()['playlists'] == 'ok'


# ---------------------------------------------------------------------------
# MediaStore.__init__ / schema
# ---------------------------------------------------------------------------


class TestMediaStoreInit:
    def test_creates_media_cache_table(self, tmp_path, mock_client, mock_error_queue):
        import sqlite3
        db = str(tmp_path / "media.db")
        MediaStore(db, mock_client, mock_error_queue)
        conn = sqlite3.connect(db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "media_cache" in tables

    def test_starts_with_empty_cache(self, store):
        assert store.playlists_has_content is False
        assert store.artists_has_content is False
        assert store.genres_has_content is False

    def test_clears_existing_data_on_construction(
            self, tmp_path, mock_client, mock_error_queue):
        db = str(tmp_path / "media.db")
        items = [_pl("Jazz", "pl:1")]
        mock_client.get_playlists.return_value = items
        store1 = MediaStore(db, mock_client, mock_error_queue)
        store1.get_playlists()
        assert store1.playlists_has_content is True

        # New instance on same DB — should start fresh
        mock_client.get_playlists.return_value = []
        store2 = MediaStore(db, mock_client, mock_error_queue)
        assert store2.playlists_has_content is False


# ---------------------------------------------------------------------------
# has_content properties
# ---------------------------------------------------------------------------


class TestHasContent:
    def test_playlists_has_content_false_before_any_fetch(self, store):
        assert store.playlists_has_content is False

    def test_playlists_has_content_true_after_fetching_non_empty(
            self, store, mock_client):
        mock_client.get_playlists.return_value = [_pl()]
        store.get_playlists()
        assert store.playlists_has_content is True

    def test_playlists_has_content_false_after_fetching_empty(
            self, store, mock_client):
        mock_client.get_playlists.return_value = []
        store.get_playlists()
        assert store.playlists_has_content is False

    def test_artists_has_content_true_after_fetching(self, store, mock_client):
        mock_client.get_artists.return_value = [_artist()]
        store.get_artists()
        assert store.artists_has_content is True

    def test_genres_has_content_true_after_fetching(self, store, mock_client):
        mock_client.get_genres.return_value = [_genre()]
        store.get_genres()
        assert store.genres_has_content is True


# ---------------------------------------------------------------------------
# get_playlists / get_artists / get_genres — cache miss
# ---------------------------------------------------------------------------


class TestGetOrFetchCacheMiss:
    def test_get_playlists_calls_client_on_miss(self, store, mock_client):
        mock_client.get_playlists.return_value = [_pl()]
        store.get_playlists()
        mock_client.get_playlists.assert_called_once()

    def test_get_playlists_returns_client_items_on_miss(self, store, mock_client):
        items = [_pl("Jazz", "pl:1")]
        mock_client.get_playlists.return_value = items
        assert store.get_playlists() == items

    def test_get_artists_calls_client_on_miss(self, store, mock_client):
        mock_client.get_artists.return_value = [_artist()]
        store.get_artists()
        mock_client.get_artists.assert_called_once()

    def test_get_genres_calls_client_on_miss(self, store, mock_client):
        mock_client.get_genres.return_value = [_genre()]
        store.get_genres()
        mock_client.get_genres.assert_called_once()

    def test_get_albums_for_artist_calls_client_on_miss(self, store, mock_client):
        mock_client.get_albums_for_artist.return_value = [_album()]
        store.get_albums_for_artist("artist:bach")
        mock_client.get_albums_for_artist.assert_called_once_with("artist:bach")

    def test_get_albums_for_artist_returns_client_items(self, store, mock_client):
        albums = [_album("WTC", "album:wtc")]
        mock_client.get_albums_for_artist.return_value = albums
        assert store.get_albums_for_artist("artist:bach") == albums


# ---------------------------------------------------------------------------
# get_playlists / get_artists / get_genres — cache hit
# ---------------------------------------------------------------------------


class TestGetOrFetchCacheHit:
    def test_get_playlists_does_not_call_client_on_hit(self, store, mock_client):
        mock_client.get_playlists.return_value = [_pl()]
        store.get_playlists()
        mock_client.get_playlists.reset_mock()
        store.get_playlists()
        mock_client.get_playlists.assert_not_called()

    def test_get_playlists_returns_cached_items(self, store, mock_client):
        items = [_pl("Jazz", "pl:1")]
        mock_client.get_playlists.return_value = items
        store.get_playlists()
        # Change what the client would return — cached value should be used
        mock_client.get_playlists.return_value = [_pl("Different", "pl:99")]
        assert store.get_playlists() == items

    def test_get_artists_uses_cache_on_second_call(self, store, mock_client):
        mock_client.get_artists.return_value = [_artist()]
        store.get_artists()
        mock_client.get_artists.reset_mock()
        store.get_artists()
        mock_client.get_artists.assert_not_called()

    def test_get_genres_uses_cache_on_second_call(self, store, mock_client):
        mock_client.get_genres.return_value = [_genre()]
        store.get_genres()
        mock_client.get_genres.reset_mock()
        store.get_genres()
        mock_client.get_genres.assert_not_called()

    def test_get_albums_uses_cache_on_second_call(self, store, mock_client):
        mock_client.get_albums_for_artist.return_value = [_album()]
        store.get_albums_for_artist("artist:bach")
        mock_client.get_albums_for_artist.reset_mock()
        store.get_albums_for_artist("artist:bach")
        mock_client.get_albums_for_artist.assert_not_called()

    def test_different_artists_cached_independently(self, store, mock_client):
        bach_albums = [_album("WTC", "album:wtc")]
        mozart_albums = [_album("Symphony 40", "album:sym40")]
        mock_client.get_albums_for_artist.side_effect = (
            lambda k: bach_albums if k == "artist:bach" else mozart_albums
        )
        store.get_albums_for_artist("artist:bach")
        store.get_albums_for_artist("artist:mozart")
        assert store.get_albums_for_artist("artist:bach") == bach_albums
        assert store.get_albums_for_artist("artist:mozart") == mozart_albums


# ---------------------------------------------------------------------------
# Empty-list is never truly cached (always re-fetches)
# ---------------------------------------------------------------------------


class TestEmptyListNotCached:
    def test_refetches_when_client_returned_empty(self, store, mock_client):
        mock_client.get_playlists.return_value = []
        store.get_playlists()
        store.get_playlists()
        assert mock_client.get_playlists.call_count == 2

    def test_caches_after_first_non_empty_result(self, store, mock_client):
        mock_client.get_playlists.side_effect = [[], [_pl()]]
        store.get_playlists()  # returns []
        store.get_playlists()  # returns [pl], now cached
        mock_client.get_playlists.reset_mock()
        store.get_playlists()  # should use cache
        mock_client.get_playlists.assert_not_called()


# ---------------------------------------------------------------------------
# remove_item
# ---------------------------------------------------------------------------


class TestMediaStoreRemoveItem:
    def test_removes_item_from_playlists_cache(self, store, mock_client):
        mock_client.get_playlists.return_value = [
            _pl("Jazz", "pl:1"), _pl("Rock", "pl:2")
        ]
        store.get_playlists()
        store.remove_item("pl:1")
        mock_client.get_playlists.reset_mock()
        result = store.get_playlists()
        assert all(i.media_key != "pl:1" for i in result)

    def test_leaves_other_items_intact(self, store, mock_client):
        mock_client.get_playlists.return_value = [
            _pl("Jazz", "pl:1"), _pl("Rock", "pl:2")
        ]
        store.get_playlists()
        store.remove_item("pl:1")
        mock_client.get_playlists.reset_mock()
        result = store.get_playlists()
        assert any(i.media_key == "pl:2" for i in result)

    def test_removes_from_artists_cache(self, store, mock_client):
        mock_client.get_artists.return_value = [
            _artist("Bach", "artist:bach"), _artist("Mozart", "artist:mozart")
        ]
        store.get_artists()
        store.remove_item("artist:bach")
        mock_client.get_artists.reset_mock()
        result = store.get_artists()
        assert all(i.media_key != "artist:bach" for i in result)

    def test_removes_from_genres_cache(self, store, mock_client):
        mock_client.get_genres.return_value = [
            _genre("Jazz", "genre:Jazz"), _genre("Rock", "genre:Rock")
        ]
        store.get_genres()
        store.remove_item("genre:Jazz")
        mock_client.get_genres.reset_mock()
        result = store.get_genres()
        assert all(i.media_key != "genre:Jazz" for i in result)

    def test_removes_from_album_cache(self, store, mock_client):
        mock_client.get_albums_for_artist.return_value = [
            _album("WTC", "album:wtc"), _album("BWV", "album:bwv")
        ]
        store.get_albums_for_artist("artist:bach")
        store.remove_item("album:wtc")
        mock_client.get_albums_for_artist.reset_mock()
        result = store.get_albums_for_artist("artist:bach")
        assert all(i.media_key != "album:wtc" for i in result)

    def test_no_op_when_nothing_cached(self, store):
        store.remove_item("nonexistent")  # must not raise

    def test_no_op_when_item_not_in_cache(self, store, mock_client):
        mock_client.get_playlists.return_value = [_pl("Jazz", "pl:1")]
        store.get_playlists()
        store.remove_item("pl:999")  # not in list
        mock_client.get_playlists.reset_mock()
        result = store.get_playlists()
        assert len(result) == 1


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


class TestRefresh:
    def test_returns_ok_for_all_categories_on_success(self, store, mock_client):
        mock_client.get_playlists.return_value = [_pl()]
        mock_client.get_artists.return_value = [_artist()]
        mock_client.get_genres.return_value = [_genre()]
        result = store.refresh()
        assert result == {"playlists": "ok", "artists": "ok", "genres": "ok"}

    def test_re_fetches_playlists_from_client(self, store, mock_client):
        store.refresh()
        mock_client.get_playlists.assert_called_once()

    def test_re_fetches_artists_from_client(self, store, mock_client):
        store.refresh()
        mock_client.get_artists.assert_called_once()

    def test_re_fetches_genres_from_client(self, store, mock_client):
        store.refresh()
        mock_client.get_genres.assert_called_once()

    def test_updates_cache_with_refreshed_playlists(self, store, mock_client):
        mock_client.get_playlists.return_value = [_pl()]
        store.refresh()
        assert store.playlists_has_content is True

    def test_updates_cache_with_refreshed_artists(self, store, mock_client):
        mock_client.get_artists.return_value = [_artist()]
        store.refresh()
        assert store.artists_has_content is True

    def test_refreshed_data_is_served_from_cache(self, store, mock_client):
        new_items = [_pl("NewPlaylist", "pl:new")]
        mock_client.get_playlists.return_value = new_items
        store.refresh()
        mock_client.get_playlists.reset_mock()
        assert store.get_playlists() == new_items
        mock_client.get_playlists.assert_not_called()

    def test_returns_error_for_failing_category(self, store, mock_client):
        mock_client.get_playlists.side_effect = RuntimeError("MPD down")
        result = store.refresh()
        assert result["playlists"] == "error"

    def test_other_categories_still_ok_when_one_fails(self, store, mock_client):
        mock_client.get_playlists.side_effect = RuntimeError("MPD down")
        mock_client.get_artists.return_value = [_artist()]
        mock_client.get_genres.return_value = [_genre()]
        result = store.refresh()
        assert result["artists"] == "ok"
        assert result["genres"] == "ok"

    def test_logs_error_when_category_fails(self, store, mock_client, mock_error_queue):
        mock_client.get_playlists.side_effect = RuntimeError("MPD down")
        store.refresh()
        mock_error_queue.log.assert_called()
        args = mock_error_queue.log.call_args[1]
        assert args["source"] == "media_store"
        assert args["severity"] == "error"

    def test_refreshes_cached_album_keys(self, store, mock_client):
        # Populate an album cache first
        mock_client.get_albums_for_artist.return_value = [_album()]
        store.get_albums_for_artist("artist:bach")
        mock_client.get_albums_for_artist.reset_mock()

        updated = [_album("New Album", "album:new")]
        mock_client.get_albums_for_artist.return_value = updated
        store.refresh()

        # Album cache for artist:bach should have been refreshed
        mock_client.get_albums_for_artist.assert_called_once_with("artist:bach")

    def test_updated_album_cache_served_after_refresh(self, store, mock_client):
        mock_client.get_albums_for_artist.return_value = [_album("Old", "album:old")]
        store.get_albums_for_artist("artist:bach")

        new_albums = [_album("New", "album:new")]
        mock_client.get_albums_for_artist.return_value = new_albums
        store.refresh()

        mock_client.get_albums_for_artist.reset_mock()
        result = store.get_albums_for_artist("artist:bach")
        assert result == new_albums
        mock_client.get_albums_for_artist.assert_not_called()

    def test_album_refresh_error_is_logged(self, store, mock_client, mock_error_queue):
        mock_client.get_albums_for_artist.return_value = [_album()]
        store.get_albums_for_artist("artist:bach")

        mock_client.get_albums_for_artist.side_effect = RuntimeError("fail")
        store.refresh()

        error_calls = mock_error_queue.log.call_args_list
        assert any("album" in str(c).lower() for c in error_calls)

    def test_does_not_refresh_uncached_album_keys(self, store, mock_client):
        store.refresh()
        # No album cache was populated, so get_albums_for_artist should not be called
        mock_client.get_albums_for_artist.assert_not_called()

    def test_refresh_overwrites_stale_playlist_cache(self, store, mock_client):
        mock_client.get_playlists.return_value = [_pl("Old", "pl:old")]
        store.get_playlists()

        mock_client.get_playlists.return_value = [_pl("Fresh", "pl:fresh")]
        store.refresh()

        mock_client.get_playlists.reset_mock()
        result = store.get_playlists()
        assert result[0].name == "Fresh"
