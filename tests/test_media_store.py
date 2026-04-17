"""Tests for MediaStore — local SQLite browse cache."""

import pytest
from unittest.mock import MagicMock
from src.interfaces import MediaItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_store(tmp_path, media_client, error_queue):
    from src.media_store import MediaStore
    return MediaStore(
        db_path=str(tmp_path / "media_cache.db"),
        media_client=media_client,
        error_queue=error_queue,
    )


def artist_item(name: str) -> MediaItem:
    return MediaItem(media_key=f"artist:{name}", name=name, media_type="artist")


# ---------------------------------------------------------------------------
# Constructor — required parameters
# ---------------------------------------------------------------------------

class TestMediaStoreRequiredParameters:
    """MediaStore must reject construction when error_queue is omitted."""

    def test_missing_error_queue_raises_type_error(
            self, tmp_path, mock_media_client):
        from src.media_store import MediaStore
        with pytest.raises(TypeError):
            MediaStore(
                db_path=str(tmp_path / "media_cache.db"),
                media_client=mock_media_client,
            )


# ---------------------------------------------------------------------------
# Refresh — error logging
# ---------------------------------------------------------------------------

class TestRefreshErrorLogging:
    """Errors during refresh() are silently swallowed but logged to the error queue."""

    def _seed_artist_albums(self, store, mock_media_client, artist_name: str) -> None:
        """Prime the store so the artist album key appears in _all_album_keys()."""
        mock_media_client.set_artists([artist_item(artist_name)])
        store.get_artists()
        store.get_albums_for_artist(f"artist:{artist_name}")

    def test_album_refresh_failure_logs_to_error_queue(
            self, tmp_path, mock_media_client, mock_error_queue):
        """When get_albums_for_artist raises during refresh, the error is logged."""
        store = make_store(tmp_path, mock_media_client, mock_error_queue)
        self._seed_artist_albums(store, mock_media_client, "Beatles")

        mock_media_client.get_albums_for_artist = MagicMock(
            side_effect=RuntimeError("MPD disconnected")
        )
        store.refresh()

        assert mock_error_queue.logged_calls, "Expected at least one error_queue.log() call"
        sources = [c[0] for c in mock_error_queue.logged_calls]
        assert "media_store" in sources

    def test_album_refresh_failure_includes_artist_in_message(
            self, tmp_path, mock_media_client, mock_error_queue):
        """The error message names the artist whose album refresh failed."""
        store = make_store(tmp_path, mock_media_client, mock_error_queue)
        self._seed_artist_albums(store, mock_media_client, "Beatles")

        mock_media_client.get_albums_for_artist = MagicMock(
            side_effect=RuntimeError("MPD error")
        )
        store.refresh()

        messages = [c[2] for c in mock_error_queue.logged_calls]
        assert any("Beatles" in m for m in messages), (
            f"Expected artist name in error message; got: {messages}"
        )

    def test_album_refresh_failure_does_not_raise(
            self, tmp_path, mock_media_client, mock_error_queue):
        """Album refresh exceptions are suppressed — refresh() still completes."""
        store = make_store(tmp_path, mock_media_client, mock_error_queue)
        self._seed_artist_albums(store, mock_media_client, "Beatles")

        mock_media_client.get_albums_for_artist = MagicMock(
            side_effect=RuntimeError("MPD error")
        )
        result = store.refresh()  # Must not raise
        assert isinstance(result, dict)

    def test_category_refresh_failure_logs_to_error_queue(
            self, tmp_path, mock_media_client, mock_error_queue):
        """When a top-level category (playlists/artists/genres) fetch raises, it is logged."""
        mock_media_client.get_playlists = MagicMock(
            side_effect=RuntimeError("MPD connection refused")
        )
        store = make_store(tmp_path, mock_media_client, mock_error_queue)
        store.refresh()

        assert mock_error_queue.logged_calls, "Expected error_queue.log() call for category failure"
        sources = [c[0] for c in mock_error_queue.logged_calls]
        assert "media_store" in sources

    def test_category_refresh_failure_includes_category_in_message(
            self, tmp_path, mock_media_client, mock_error_queue):
        """The error message names the failing category."""
        mock_media_client.get_artists = MagicMock(
            side_effect=RuntimeError("MPD error")
        )
        store = make_store(tmp_path, mock_media_client, mock_error_queue)
        store.refresh()

        messages = [c[2] for c in mock_error_queue.logged_calls]
        assert any("artist" in m.lower() for m in messages), (
            f"Expected category name in error message; got: {messages}"
        )

    def test_category_refresh_failure_still_returns_error_in_summary(
            self, tmp_path, mock_media_client, mock_error_queue):
        """Category errors still appear in the summary dict as 'error' (existing behaviour)."""
        mock_media_client.get_artists = MagicMock(side_effect=Exception("fail"))
        store = make_store(tmp_path, mock_media_client, mock_error_queue)
        result = store.refresh()
        assert result["artists"] == "error"

    def test_successful_refresh_logs_no_errors(
            self, tmp_path, mock_media_client, mock_error_queue):
        """When all fetches succeed, nothing is logged to the error queue."""
        store = make_store(tmp_path, mock_media_client, mock_error_queue)
        store.refresh()
        assert mock_error_queue.logged_calls == []
