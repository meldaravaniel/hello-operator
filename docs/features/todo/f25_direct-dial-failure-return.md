### F-25 · Re-deliver the prior menu after a failed direct dial

**Background**
When `_execute_direct_dial()` fails (number not found), it speaks `SCRIPT_NOT_IN_SERVICE` and sets `self._state = MenuState.IDLE_MENU` — a bare state assignment with no menu announcement. The user hears "not in service" and then silence. They have no idea what options are available and must blindly dial `0` or wait 30 s for the inactivity timeout.

This affects two scenarios:
1. **Normal flow** — user hears a browse menu, dials two digits quickly to enter direct dial, number not found → silence.
2. **Early-dial flow** — user dials before the idle menu is delivered (two quick digits bypass the f11 guard), number not found → user has never heard any menu, yet lands in `IDLE_MENU` with no announcement.

After "not in service", the user should hear whichever menu they were in when they started dialing.

**Changes required**

1. **Add `_pre_dial_state`** — a new `Optional[MenuState]` instance variable (initialised to `None` in `__init__`, cleared in `on_handset_on_cradle`).

2. **Save state in `_enter_direct_dial`** — before overwriting `self._state`:
   ```python
   self._pre_dial_state = self._state
   self._state = MenuState.DIRECT_DIAL
   ```

3. **Restore and re-deliver in `_execute_direct_dial` on failure** — replace the bare state assignment:
   ```python
   # Before:
   self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
   self._state = MenuState.IDLE_MENU

   # After:
   self._tts.speak_and_play(SCRIPT_NOT_IN_SERVICE)
   pre = self._pre_dial_state or MenuState.IDLE_MENU
   if pre == MenuState.IDLE_DIAL_TONE:
       # User dialed before any menu was delivered — determine correct top-level menu
       playback = self._plex_client.now_playing()
       if playback.item is not None:
           self._deliver_playing_menu(playback, now)
       else:
           self._deliver_idle_menu(now)
   else:
       self._state = pre
       self._re_deliver_current_state(now)
   ```

**Acceptance criteria**
- Failed direct dial from `IDLE_MENU` → speaks "not in service" then re-delivers the idle menu.
- Failed direct dial from `BROWSE_ARTISTS` (or any other browse state) → speaks "not in service" then re-delivers that browse prompt.
- Failed direct dial dialed before any menu was delivered (`IDLE_DIAL_TONE`) → speaks "not in service" then delivers the correct top-level menu (idle or playing based on `now_playing()`).
- Successful direct dial is unaffected.
- New tests cover all three failure scenarios above.
- All existing tests pass.
