### F-16 · `has_content` properties use existence check instead of full deserialize

**Background**
`PlexStore.playlists_has_content`, `artists_has_content`, and `genres_has_content` each read the full JSON blob from SQLite and deserialize it into a `List[MediaItem]` just to evaluate `bool(items)`. These are called multiple times per session start from `_deliver_idle_menu`. For large libraries this is wasteful.

**Changes required**

Replace the full read with a lightweight existence query:

```python
@property
def playlists_has_content(self) -> bool:
    with self._connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM plex_cache WHERE cache_key = ? AND data != '[]'",
            (_KEY_PLAYLISTS,)
        ).fetchone()
    return row is not None
```

Apply the same pattern to `artists_has_content` and `genres_has_content`.

**Acceptance criteria**
- Properties return `True` when the corresponding cache entry exists and is non-empty.
- Properties return `False` when the entry is absent or is `'[]'`.
- `MockPlexStore` `has_content` properties continue to work as before (they are already in-memory booleans and need no change).

**Testable outcome**
- Input: write `'[]'` to `plex_cache` for `"playlists"`; call `playlists_has_content`.
- Expected: returns `False`.
- Input: write `'[{"plex_key": "1", "name": "A", "media_type": "playlist"}]'`; call `playlists_has_content`.
- Expected: returns `True`.