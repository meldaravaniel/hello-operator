### F-19 · Remove duplicate auth token from Plex playback request params

**Background**
The `_headers` dict in `PlexClient` already contains `"X-Plex-Token": token`. Each playback method (`play`, `shuffle_all`, `pause`, `unpause`, `skip`, `stop`) also adds `"X-Plex-Token": self._token` to the `params` dict, sending the token twice per request.

**Changes required**

Remove `"X-Plex-Token": self._token` from the `params` dict in each of the six playback methods. The token in `_headers` is sufficient.

**Acceptance criteria**
- Outgoing playback requests contain `X-Plex-Token` exactly once (in the `Authorization` header, not in query params).
- All existing unit tests pass.