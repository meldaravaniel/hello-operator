### F-13 · Idle menu retry fetches all categories, not just playlists

**Background**
In `_handle_idle_menu_digit` with `_failure_mode == "plex"`, the retry calls only `plex_store.get_playlists()`. If the original failure was fetching artists or genres, a successful playlist fetch clears `_failure_mode` and calls `_deliver_idle_menu()`, which may immediately fail again on artists or genres, re-entering the failure loop in a confusing way.

**Changes required**

Replace the single `get_playlists()` call in the retry path with a call to `plex_store.refresh()`, which re-fetches all categories and returns a summary dict. If all categories return `"error"`, keep `_failure_mode` set and re-speak the failure and retry prompts. If at least one category returns `"ok"`, clear `_failure_mode` and call `_deliver_idle_menu()`.

**Acceptance criteria**
- A retry attempt that succeeds for playlists but fails for artists proceeds to the menu showing only the successfully fetched categories.
- A retry attempt that fails for all categories re-speaks the failure prompt and retry option.
- A complete success clears failure mode and delivers the full menu.

**Testable outcome**
- Input: mock `plex_store.refresh()` to return `{'playlists': 'ok', 'artists': 'error', 'genres': 'error'}`; dial `1` in failure mode.
- Expected: `_failure_mode` is `None`; `_deliver_idle_menu` called; only playlists offered in menu.