### F-09 · Browse and artist selection connecting announcement

**Background**
`_select_item()` for playlists, genres, and albums calls `plex_client.play()` and transitions to `PLAYING_MENU` without speaking `SCRIPT_CONNECTING_TEMPLATE`. Only the direct-dial path announces the connection. The spec describes the template for all final selections.

**Changes required**

In `_select_item()`, before calling `plex_client.play()` for non-artist items:
1. Assign or retrieve the phone number via `phone_book.assign_or_get(item.plex_key, item.media_type, item.name)`.
2. Build `digit_words_str` from the phone number digits using `_DIGIT_WORDS`.
3. Speak `SCRIPT_CONNECTING_TEMPLATE.format(digits=digit_words_str, name=item.name)`.
4. Then call `plex_client.play(item.plex_key)`.

Similarly, in `_handle_artist_submenu_digit` when digit `1` is pressed (shuffle artist):
1. Retrieve the phone number for the current artist.
2. Speak the connecting template.
3. Then call `plex_client.play(self._current_artist.plex_key)`.

**Acceptance criteria**
- Selecting any playlist, album, or genre speaks the connecting template before playback begins.
- Selecting artist shuffle (digit 1 in artist submenu) speaks the connecting template.
- The phone number spoken matches the entry in the phone book.
- State is `PLAYING_MENU` after the announcement.

**Testable outcome**
- Input: set up mock store with one playlist; navigate to `BROWSE_PLAYLISTS`; dial the listing digit.
- Expected: `mock_tts.speak_and_play` called with text matching `SCRIPT_CONNECTING_TEMPLATE`; `mock_plex.play` called with the playlist's plex_key; `menu.state == MenuState.PLAYING_MENU`.