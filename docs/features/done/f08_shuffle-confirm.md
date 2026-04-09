### F-08 · Shuffle confirmation announcement and state transition

**Background**
When the user selects the shuffle option in `_handle_idle_menu_digit`, `plex_client.shuffle_all()` is called but no TTS announcement is made and the state remains `IDLE_MENU`. The user gets silence. The system should announce the connection and transition to `PLAYING_MENU`.

**Changes required**

After `plex_client.shuffle_all()`:
1. Speak `SCRIPT_CONNECTING_TEMPLATE` with a placeholder name (e.g., `"the general exchange"`) and the digits spoken as the configured shuffle option digit.
2. Transition state to `PLAYING_MENU`.

Determine whether `SCRIPT_CONNECTING_TEMPLATE` fits the shuffle use case or if a dedicated shuffle confirmation script (`SCRIPT_SHUFFLE_CONNECTING`) is more appropriate. The script text should be added to `SCRIPTS.md` and pre-rendered.

**Acceptance criteria**
- After dialing the shuffle option, the user hears a connection announcement before music starts.
- State transitions to `PLAYING_MENU`.
- Hanging up after shuffle confirmation leaves music playing (existing hang-up behaviour).

**Testable outcome**
- Input: mock `plex_store` with artists present; call `on_digit(shuffle_digit)` in `IDLE_MENU` state.
- Expected: `mock_plex.shuffle_all` called; `mock_tts.speak_and_play` called with connecting text; `menu.state == MenuState.PLAYING_MENU`.