### F-04 · Audio worker thread with queued playback

**Background**
All audio methods (`play_tone`, `play_file`, `play_off_hook_tone`) block the calling thread. `PiperTTS.speak_and_play()` calls `audio.play_file()` synchronously, so every TTS utterance freezes the main event loop for the full audio duration. During this time `gpio.poll()` is never called, so `HANDSET_ON_CRADLE` events are lost. The spec requires: *"Hang-up stops all local audio immediately — even mid-TTS."*

**Design**
Introduce a dedicated audio worker thread inside `SounddeviceAudio`:

- An internal `queue.Queue` holds audio tasks. Each task is a callable (e.g., `lambda: sd.play(...); sd.wait()`).
- The worker thread loops: dequeue a task, execute it, repeat.
- `stop()` clears the queue, sets the existing `_stop_event`, and calls `sd.stop()` — this terminates both the currently-playing audio and any queued items.
- All public methods (`play_tone`, `play_file`, `play_dtmf`, `play_off_hook_tone`) become non-blocking: they enqueue a task and return immediately.
- `is_playing()` returns `True` if the worker is currently executing a task or the queue is non-empty.
- The worker thread is a daemon thread started in `__init__`.

The main event loop in `main.py` gains back full GPIO polling responsiveness. `speak_and_play` sequences (e.g., opener → greeting → hint) remain ordered because tasks are FIFO.

**Acceptance criteria**
- Calling `audio.stop()` while audio is playing terminates playback within one polling cycle (~5 ms).
- Multi-step TTS sequences play in the correct order.
- `is_playing()` returns `False` promptly after `stop()` or after the queue drains.
- All existing `MockAudio`-based unit tests continue to pass unchanged (the mock is unaffected).
- A new test demonstrates that `stop()` called during `play_tone` results in no further audio output.

**Testable outcome**
- Input: enqueue a 5-second tone, then call `stop()` after 100 ms.
- Expected: audio halts within ~5 ms of `stop()`; `is_playing()` returns `False`; no additional audio plays.