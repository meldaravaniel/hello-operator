"""Backward-compatibility shim — this module has been renamed to media_store.py."""

from src.media_store import (
    MediaStore as PlexStore,
    MockMediaStore as MockPlexStore,
    _KEY_PLAYLISTS,
    _KEY_ARTISTS,
    _KEY_GENRES,
)

__all__ = ["PlexStore", "MockPlexStore", "_KEY_PLAYLISTS", "_KEY_ARTISTS", "_KEY_GENRES"]
