### F-02 · Fix Piper TTS output format

**Background**
`_run_piper()` invokes Piper with `--output-raw`, which writes raw 16-bit LE PCM to stdout — no WAV header. These bytes are saved to `<name>.wav` and later opened with `wave.open()`, which requires a RIFF/WAV header and raises `wave.Error`.

**Changes required**
Replace the `--output-raw` flag with Piper's `--output_file <path>` option so Piper writes a proper WAV file directly. Adjust `_run_piper()` to accept an output path, write to that path, and return success/failure rather than raw bytes.

Alternatively, if stdout capture is required, construct a valid WAV header around the raw PCM before writing to disk. The `--output-raw` PCM format for the default Piper models is 16-bit signed LE, 22050 Hz, mono.

**Acceptance criteria**
- Pre-rendered script WAV files can be opened with `wave.open()` without error.
- `audio.play_file()` successfully plays a pre-rendered script.
- Live synthesis WAV files are also valid.

**Testable outcome**
- Input: call `tts.prerender({"test": "hello world"})` with a real Piper binary.
- Expected: `<cache_dir>/test.wav` is a valid WAV file (passes `wave.open()`, has nonzero frame count).