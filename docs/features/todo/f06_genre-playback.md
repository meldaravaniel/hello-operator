### F-06 · Genre playback via track queue

**Background**
The Plex genre browse API returns a path-style key (e.g., `/library/sections/1/genre/Jazz`) rather than a `ratingKey`. This path cannot be passed to `play()`. Genre playback requires fetching all tracks under the genre and starting a shuffled queue.

**Changes required**

1. Add `get_tracks_for_genre(section_id: str, genre_key: str) -> list` to `PlexClientInterface` and `PlexClient`. This method calls `/library/sections/{section_id}/all?genre={genre_key}` (or the equivalent Plex filter path) and returns a list of track `ratingKey` values.

2. Add `play_tracks(track_keys: list, shuffle: bool = True) -> None` to `PlexClientInterface` and `PlexClient`. This creates a Plex play queue from the provided keys and starts playback. (Plex API: `POST /playQueues` with `uri` and `shuffle=1`.)

3. Store the `section_id` in `MediaItem` for genre items — or encode it into `plex_key` in a parseable format (e.g., `"section:1/genre:Jazz"`). The `plex_key` field currently conflates the browse path with the playable key.

4. Update `PlexStore.get_genres()` and `PlexClient.get_genres()` to capture the `section_id` alongside each genre.

5. Update `menu._select_item()` to detect `media_type == "genre"` and call `plex_client.get_tracks_for_genre(...)` + `plex_client.play_tracks(...)` instead of the generic `plex_client.play()`.

6. Update `MockPlexClient` to add stub implementations of the two new methods.

**Acceptance criteria**
- Selecting a genre causes the local Plex player to begin playing tracks from that genre in shuffled order.
- If a genre has no tracks, `SCRIPT_NOT_IN_SERVICE` is spoken and the user is returned to the browse state.
- Existing playlist and artist playback is unaffected.

**Testable outcome (unit)**
- Input: mock `get_tracks_for_genre` returning `["key1", "key2"]`; select a genre item in the menu.
- Expected: `play_tracks(["key1", "key2"], shuffle=True)` is called; state transitions to `PLAYING_MENU`.