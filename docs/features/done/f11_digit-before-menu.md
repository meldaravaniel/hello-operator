### F-11 · Digit received before dial-tone menu is delivered

**Background**
If a digit is dialed during the `IDLE_DIAL_TONE` window (before the timeout fires the menu), disambiguation queues it. When the disambiguation timeout fires, `_dispatch_navigation_digit` is called while state is still `IDLE_DIAL_TONE`. The menu options check runs without having first delivered the menu prompt, and the dial tone may still be playing.

**Changes required**

In `_dispatch_navigation_digit`, add a guard at the top:

```python
if self._state == MenuState.IDLE_DIAL_TONE:
    # Deliver the appropriate menu first, then process the digit
    self._audio.stop()
    playback = self._plex_client.now_playing()
    if playback.item is not None:
        self._deliver_playing_menu(playback, now)
    else:
        self._deliver_idle_menu(now)
    # After menu delivery, process the digit against the new state
```

Because `_deliver_idle_menu` and `_deliver_playing_menu` are synchronous in the current architecture (they speak the menu), the digit would be processed after the full menu prompt. Consider whether the digit should be silently dropped in this case (user dialed before hearing options) or processed (user knew what they wanted). The safer default is to drop it and let the user dial again after hearing the menu.

**Acceptance criteria**
- A digit dialed during `IDLE_DIAL_TONE` does not cause an invalid state routing.
- The menu prompt is spoken before any navigation action is taken.
- The dial tone is stopped before the menu prompt begins.

**Testable outcome**
- Input: call `on_handset_lifted(now=0)`; call `on_digit(1, now=0.1)` (well within `DIAL_TONE_TIMEOUT_IDLE=5s`); advance `tick` to `now=1.7` (past disambiguation timeout).
- Expected: state is `IDLE_MENU` (menu was delivered); no `SCRIPT_NOT_IN_SERVICE` spoken; dial tone stopped.