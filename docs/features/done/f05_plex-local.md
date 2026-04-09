### F-05 · Plex local player targeting

**Background**
The playback methods (`play`, `pause`, `unpause`, `skip`, `stop`) use `/player/playback/...`, the Plex server's player-proxy API. This API requires the caller to identify which registered Plex player to target via `X-Plex-Target-Client-Identifier`. Without it, the server cannot route the command. The target is the Plex player running locally on the Pi.

**Changes required**

1. Add a new constant `PLEX_PLAYER_IDENTIFIER` to `constants.py` (with a TODO comment) representing the machine identifier of the local Plex player (found in the player's settings or via `/clients`).

2. Update `PlexClient.__init__` to accept `player_identifier: str` and store it.

3. Add `X-Plex-Target-Client-Identifier: <player_identifier>` to the headers sent with all playback commands. Also add an incrementing `commandID` parameter, as some Plex proxy implementations require it to order commands. Store a `_command_id` counter on the instance, incrementing with each playback call.

4. Update `main.py` to pass `PLEX_PLAYER_IDENTIFIER` when constructing `PlexClient`.

5. Remove the duplicate `X-Plex-Token` from the `params` dict in each playback method — it is already in `_headers`.

**Acceptance criteria**
- Calling `plex_client.play(plex_key)` with a valid key causes the local Plex player to begin playback.
- Calling `pause()`, `unpause()`, `skip()`, `stop()` produces the expected state change on the local player.
- `commandID` increments on each call.
- `X-Plex-Token` appears exactly once per request (in headers, not query params).

**Testable outcome (unit)**
- Input: construct `PlexClient` with a `player_identifier` of `"test-machine-123"` and call `pause()`.
- Expected: the outgoing request includes `X-Plex-Target-Client-Identifier: test-machine-123` in headers and `commandID=1` (or similar) in params; `X-Plex-Token` does not appear in params.

**Testable outcome (integration)**
- Input: call `plex_client.play(<valid_plex_key>)` against a real server with the Pi's player running.
- Expected: the local Plex player begins playing the specified item within ~2 seconds.
