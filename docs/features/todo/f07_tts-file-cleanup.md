### F-07 · TTS temp file cleanup

**Background**
`PiperTTS._synthesize()` creates a file with `tempfile.mkstemp()` for live synthesis but never deletes it. Every dynamic string (media name, error message, phone number) that goes through live synthesis leaves a `.wav` file in the system temp directory permanently.

**Changes required**

Use a dedicated temp directory under `TTS_CACHE_DIR` (e.g., `<cache_dir>/live/`) for live synthesis files. At `__init__` time, clear this directory. After `audio.play_file(path)` completes (or after enqueueing, once the audio worker signals completion), delete the file.

If the worker-thread model from F-04 is in place, the cleanup callback can be registered as a follow-up task in the queue (a no-op audio task that deletes the file after the preceding play task drains).

Alternatively, if simplicity is preferred: wipe `<cache_dir>/live/` at startup and let files accumulate per session (bounded by session length).

**Acceptance criteria**
- After the application shuts down cleanly, no live-synthesis `.wav` files remain in the temp location.
- Pre-rendered cache files are not affected.

**Testable outcome**
- Input: call `tts.speak_and_play("some dynamic text")` for a string that is not pre-rendered.
- Expected: a temp `.wav` file is created; after playback completes, the file is removed.