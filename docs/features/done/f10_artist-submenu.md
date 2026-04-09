### F-10 · Artist submenu re-delivery on back navigation

**Background**
`_re_deliver_current_state()` handles `IDLE_MENU`, `PLAYING_MENU`, and all `BROWSE_*` states but not `ARTIST_SUBMENU`. If the system ends up needing to re-deliver `ARTIST_SUBMENU` (e.g., after an invalid digit), the method silently does nothing, leaving the user in silence.

**Changes required**

Add an `ARTIST_SUBMENU` case to `_re_deliver_current_state()`:

```python
elif self._state == MenuState.ARTIST_SUBMENU:
    if self._current_artist:
        albums = self._plex_store.get_albums_for_artist(self._current_artist.plex_key)
        text = SCRIPT_ARTIST_SUBMENU_TEMPLATE.format(artist=self._current_artist.name)
        if albums:
            text += SCRIPT_ARTIST_SUBMENU_ALBUMS_SUFFIX
        self._tts.speak_and_play(text)
```

**Acceptance criteria**
- Dialing an invalid digit while in `ARTIST_SUBMENU` speaks `SCRIPT_NOT_IN_SERVICE` followed by a re-read of the artist submenu options.
- `_current_artist` is preserved through the re-delivery.

**Testable outcome**
- Input: navigate to `ARTIST_SUBMENU` for a mock artist with albums; dial digit `5` (invalid).
- Expected: `mock_tts.speak_and_play` called with `SCRIPT_NOT_IN_SERVICE`; then called again with text containing the artist name and album option.