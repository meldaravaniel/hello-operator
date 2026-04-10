"""Tests for src/tts.py — PiperTTS concrete implementation.

Piper binary is mocked so tests don't require it installed.
ErrorQueueInterface is mocked for all tests that expect error logging.
"""

import os
import json
import hashlib
import time
import pytest
from unittest.mock import MagicMock, patch, call
from src.tts import PiperTTS, MockTTS
from src.audio import MockAudio
from src.error_queue import MockErrorQueue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_piper(tmp_path):
    """
    Return a callable that acts as a fake Piper subprocess.

    Compatible with both the old --output-raw interface (returns WAV bytes via
    stdout) and the new --output_file interface (writes a WAV file to the path
    given by --output_file in cmd).  This lets existing tests continue to work
    after the implementation is updated to use --output_file.
    """
    def fake_piper(cmd, stdin, stdout, stderr, **kwargs):
        import wave, array, io
        # Build a minimal valid WAV in memory
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            samples = array.array('h', [100] * 2205)
            wf.writeframes(samples.tobytes())
        wav_bytes = buf.getvalue()

        # If --output_file is present, write the WAV there (new interface)
        for i, arg in enumerate(cmd):
            if arg == "--output_file" and i + 1 < len(cmd):
                with open(cmd[i + 1], 'wb') as f:
                    f.write(wav_bytes)
                break

        proc = MagicMock()
        proc.communicate.return_value = (wav_bytes, b'')
        proc.returncode = 0
        return proc

    return fake_piper


def _make_file_based_piper():
    """
    Return a callable that simulates Piper's --output_file mode: reads the
    output path from the --output_file argument in cmd and writes a valid WAV
    file there directly (no stdout capture).
    """
    def fake_piper(cmd, stdin, stdout, stderr, **kwargs):
        import wave, array
        # Find --output_file <path> in cmd
        output_path = None
        for i, arg in enumerate(cmd):
            if arg == "--output_file" and i + 1 < len(cmd):
                output_path = cmd[i + 1]
                break
        proc = MagicMock()
        if output_path is None:
            # --output_file not present — simulate failure
            proc.communicate.return_value = (b'', b'error: --output_file required')
            proc.returncode = 1
            return proc
        # Write a tiny valid WAV file to the output path
        with wave.open(output_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            samples = array.array('h', [100] * 2205)
            wf.writeframes(samples.tobytes())
        proc.communicate.return_value = (b'', b'')
        proc.returncode = 0
        return proc

    return fake_piper


def make_tts(tmp_path, error_queue=None):
    """Build a PiperTTS with a temp cache dir and fake Piper binary."""
    cache_dir = str(tmp_path / "tts_cache")
    os.makedirs(cache_dir, exist_ok=True)
    audio = MockAudio()
    if error_queue is None:
        error_queue = MockErrorQueue()
    return PiperTTS(
        piper_binary="/fake/piper",
        piper_model="/fake/model.onnx",
        cache_dir=cache_dir,
        audio=audio,
        error_queue=error_queue,
    ), audio, error_queue, cache_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSpeak:

    def test_speak_returns_audio_path(self, tmp_path):
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        with patch('subprocess.Popen', side_effect=_make_fake_piper(tmp_path)):
            path = tts.speak("hello world")
        assert path is not None
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0

    def test_speak_and_play_calls_audio_interface(self, tmp_path):
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        with patch('subprocess.Popen', side_effect=_make_fake_piper(tmp_path)):
            tts.speak_and_play("hello world")
        play_calls = [c for c in audio.calls if c[0] == 'play_file']
        # play_file must have been called once; the file is cleaned up afterward
        assert len(play_calls) == 1

    def test_speak_digits_individual(self, tmp_path):
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        stdin_inputs = []

        def capture_piper(cmd, stdin, stdout, stderr, **kwargs):
            import io, wave, array
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(22050)
                samples = array.array('h', [100] * 2205)
                wf.writeframes(samples.tobytes())
            proc = MagicMock()
            # Capture what text will be passed via communicate()
            def fake_communicate(input=None):
                if input:
                    stdin_inputs.append(input.decode())
                return (buf.getvalue(), b'')
            proc.communicate.side_effect = fake_communicate
            proc.returncode = 0
            return proc

        with patch('subprocess.Popen', side_effect=capture_piper):
            tts.speak_digits("5551234")

        assert stdin_inputs, "No text was passed to Piper"
        full_text = " ".join(stdin_inputs).lower()
        for word in ['five', 'one', 'two', 'three', 'four']:
            assert word in full_text, f"'{word}' not found in spoken text: {full_text}"


class TestPrerender:

    def test_prerender_creates_files(self, tmp_path):
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        prompts = {
            "SCRIPT_GREETING": "Hello, how may I help you?",
            "SCRIPT_GOODBYE": "Goodbye, have a nice day.",
        }
        with patch('subprocess.Popen', side_effect=_make_fake_piper(tmp_path)):
            tts.prerender(prompts)

        for script_name in prompts:
            wav_path = os.path.join(cache_dir, f"{script_name}.wav")
            assert os.path.exists(wav_path), f"Missing {wav_path}"
            assert os.path.getsize(wav_path) > 0

    def test_prerender_stores_hash(self, tmp_path):
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        prompts = {"SCRIPT_GREETING": "Hello there."}
        with patch('subprocess.Popen', side_effect=_make_fake_piper(tmp_path)):
            tts.prerender(prompts)

        hash_path = os.path.join(cache_dir, "SCRIPT_GREETING.hash")
        assert os.path.exists(hash_path)
        stored_hash = open(hash_path).read().strip()
        expected = hashlib.md5("Hello there.".encode()).hexdigest()
        assert stored_hash == expected

    def test_prerender_skips_unchanged_scripts(self, tmp_path):
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        prompts = {"SCRIPT_GREETING": "Hello there."}
        call_count = [0]

        def counting_piper(cmd, stdin, stdout, stderr, **kwargs):
            call_count[0] += 1
            return _make_fake_piper(tmp_path)(cmd, stdin, stdout, stderr)

        with patch('subprocess.Popen', side_effect=counting_piper):
            tts.prerender(prompts)
            first_count = call_count[0]
            tts.prerender(prompts)
            second_count = call_count[0]

        assert first_count > 0
        assert second_count == first_count  # No additional Piper calls

    def test_prerender_rerenders_on_text_change(self, tmp_path):
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        call_count = [0]

        def counting_piper(cmd, stdin, stdout, stderr, **kwargs):
            call_count[0] += 1
            return _make_fake_piper(tmp_path)(cmd, stdin, stdout, stderr)

        with patch('subprocess.Popen', side_effect=counting_piper):
            tts.prerender({"SCRIPT_GREETING": "Hello."})
            count_after_first = call_count[0]
            tts.prerender({"SCRIPT_GREETING": "Hello, world."})  # Changed text
            count_after_second = call_count[0]

        assert count_after_second > count_after_first

    def test_prerender_rerenders_on_missing_file(self, tmp_path):
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        prompts = {"SCRIPT_GREETING": "Hello."}
        call_count = [0]

        def counting_piper(cmd, stdin, stdout, stderr, **kwargs):
            call_count[0] += 1
            return _make_fake_piper(tmp_path)(cmd, stdin, stdout, stderr)

        with patch('subprocess.Popen', side_effect=counting_piper):
            tts.prerender(prompts)
            # Delete the WAV file but keep the hash
            wav_path = os.path.join(cache_dir, "SCRIPT_GREETING.wav")
            os.remove(wav_path)
            tts.prerender(prompts)

        assert call_count[0] == 2  # Re-synthesized because WAV was missing

    def test_prerender_cache_persists_across_instantiation(self, tmp_path):
        """Cache files remain usable after PiperTTS is re-created."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        prompts = {"SCRIPT_GREETING": "Hello."}
        call_count = [0]

        def counting_piper(cmd, stdin, stdout, stderr, **kwargs):
            call_count[0] += 1
            return _make_fake_piper(tmp_path)(cmd, stdin, stdout, stderr)

        with patch('subprocess.Popen', side_effect=counting_piper):
            tts.prerender(prompts)
            first_count = call_count[0]

        # Re-create TTS with same cache_dir
        tts2 = PiperTTS(
            piper_binary="/fake/piper",
            piper_model="/fake/model.onnx",
            cache_dir=cache_dir,
            audio=audio,
            error_queue=eq,
        )
        with patch('subprocess.Popen', side_effect=counting_piper):
            tts2.prerender(prompts)

        assert call_count[0] == first_count  # No re-synthesis


class TestSpeakAndPlayCache:

    def test_speak_and_play_uses_cache_for_prerendered(self, tmp_path):
        """After prerender, speak_and_play with known text uses cache; no Piper."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        text = "Hello, operator speaking."
        script_name = "SCRIPT_GREETING"

        with patch('subprocess.Popen', side_effect=_make_fake_piper(tmp_path)):
            tts.prerender({script_name: text})

        piper_call_count = [0]

        def fail_if_called(cmd, stdin, stdout, stderr, **kwargs):
            piper_call_count[0] += 1
            return _make_fake_piper(tmp_path)(cmd, stdin, stdout, stderr)

        with patch('subprocess.Popen', side_effect=fail_if_called):
            tts.speak_and_play(text)

        assert piper_call_count[0] == 0, "Piper was called for a cached script"

    def test_cache_miss_falls_back_to_live(self, tmp_path):
        """Cached file deleted → speak_and_play falls back to live synthesis."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        text = "Hello operator."
        script_name = "SCRIPT_GREETING"

        with patch('subprocess.Popen', side_effect=_make_fake_piper(tmp_path)):
            tts.prerender({script_name: text})

        # Delete the cached WAV
        wav_path = os.path.join(cache_dir, f"{script_name}.wav")
        os.remove(wav_path)

        # Should fall back to live synthesis without raising
        with patch('subprocess.Popen', side_effect=_make_fake_piper(tmp_path)):
            tts.speak_and_play(text)  # Must not raise

    def test_cache_miss_logs_warning(self, tmp_path):
        """Cache miss → warning logged to error queue."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        text = "Hello operator."
        script_name = "SCRIPT_GREETING"

        with patch('subprocess.Popen', side_effect=_make_fake_piper(tmp_path)):
            tts.prerender({script_name: text})

        wav_path = os.path.join(cache_dir, f"{script_name}.wav")
        os.remove(wav_path)

        with patch('subprocess.Popen', side_effect=_make_fake_piper(tmp_path)):
            tts.speak_and_play(text)

        warnings = [e for e in eq.entries if e.severity == 'warning']
        assert len(warnings) >= 1

    def test_cache_miss_attempts_repopulate(self, tmp_path):
        """Cache miss → system attempts to recreate the missing file."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        text = "Hello."
        script_name = "SCRIPT_GREETING"

        with patch('subprocess.Popen', side_effect=_make_fake_piper(tmp_path)):
            tts.prerender({script_name: text})

        wav_path = os.path.join(cache_dir, f"{script_name}.wav")
        os.remove(wav_path)

        repopulate_calls = [0]

        def counting_piper(cmd, stdin, stdout, stderr, **kwargs):
            repopulate_calls[0] += 1
            return _make_fake_piper(tmp_path)(cmd, stdin, stdout, stderr)

        with patch('subprocess.Popen', side_effect=counting_piper):
            tts.speak_and_play(text)

        assert repopulate_calls[0] >= 1


class TestCacheRepopulateRetry:

    def test_cache_repopulate_retries_with_backoff(self, tmp_path):
        """Repopulation failure → retried up to CACHE_RETRY_MAX times."""
        from src.constants import CACHE_RETRY_MAX
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        text = "Hello."
        script_name = "SCRIPT_GREETING"

        with patch('subprocess.Popen', side_effect=_make_fake_piper(tmp_path)):
            tts.prerender({script_name: text})

        wav_path = os.path.join(cache_dir, f"{script_name}.wav")
        os.remove(wav_path)

        fail_count = [0]

        def always_fail(cmd, stdin, stdout, stderr, **kwargs):
            fail_count[0] += 1
            proc = MagicMock()
            proc.communicate.return_value = (b'', b'error')
            proc.returncode = 1
            return proc

        with patch('subprocess.Popen', side_effect=always_fail):
            with patch('time.sleep'):  # don't actually sleep
                tts.speak_and_play(text)

        # CACHE_RETRY_MAX attempts during repopulation (plus possible fallback synthesis)
        assert fail_count[0] >= CACHE_RETRY_MAX

    def test_cache_repopulate_exhausted_logs_error(self, tmp_path):
        """Retries exhausted → persistent error logged."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        text = "Hello."
        script_name = "SCRIPT_GREETING"

        with patch('subprocess.Popen', side_effect=_make_fake_piper(tmp_path)):
            tts.prerender({script_name: text})

        os.remove(os.path.join(cache_dir, f"{script_name}.wav"))

        def always_fail(cmd, stdin, stdout, stderr, **kwargs):
            proc = MagicMock()
            proc.communicate.return_value = (b'', b'error')
            proc.returncode = 1
            return proc

        with patch('subprocess.Popen', side_effect=always_fail):
            with patch('time.sleep'):
                tts.speak_and_play(text)

        errors = [e for e in eq.entries if e.severity == 'error']
        assert len(errors) >= 1


class TestPiperFailure:

    def test_piper_failure_logs_error(self, tmp_path):
        """Piper binary non-functional → error logged."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)

        def fail_piper(cmd, stdin, stdout, stderr, **kwargs):
            proc = MagicMock()
            proc.communicate.return_value = (b'', b'error')
            proc.returncode = 1
            return proc

        with patch('subprocess.Popen', side_effect=fail_piper):
            tts.speak_and_play("some text")

        errors = [e for e in eq.entries if e.severity == 'error']
        assert len(errors) >= 1

    def test_piper_failure_plays_off_hook_tone(self, tmp_path):
        """Piper binary non-functional → off-hook warning tone plays."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)

        def fail_piper(cmd, stdin, stdout, stderr, **kwargs):
            proc = MagicMock()
            proc.communicate.return_value = (b'', b'error')
            proc.returncode = 1
            return proc

        with patch('subprocess.Popen', side_effect=fail_piper):
            tts.speak_and_play("some text")

        off_hook_calls = [c for c in audio.calls if c[0] == 'play_off_hook_tone']
        assert len(off_hook_calls) >= 1


# ---------------------------------------------------------------------------
# WAV file validity (F-02: fix Piper output format)
# ---------------------------------------------------------------------------

class TestWavValidity:
    """
    Verify that PiperTTS produces files that are valid WAV (RIFF) files,
    openable with wave.open() and containing nonzero frames.

    Uses _make_file_based_piper which simulates Piper's --output_file mode:
    it reads the output path from the command arguments and writes a real WAV
    file there.  If _run_piper still uses --output-raw (the old bug), the
    helper returns returncode=1 and no file is written, causing the tests to
    fail.
    """

    def test_prerender_produces_valid_wav(self, tmp_path):
        """Pre-rendered script files must be openable with wave.open()."""
        import wave
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        prompts = {"SCRIPT_GREETING": "Hello, operator speaking."}
        with patch('subprocess.Popen', side_effect=_make_file_based_piper()):
            tts.prerender(prompts)

        wav_path = os.path.join(cache_dir, "SCRIPT_GREETING.wav")
        assert os.path.exists(wav_path), "WAV file was not created"
        with wave.open(wav_path, 'rb') as wf:
            assert wf.getnframes() > 0, "WAV file has no audio frames"

    def test_speak_produces_valid_wav(self, tmp_path):
        """speak() must return a path to a valid WAV file."""
        import wave
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        with patch('subprocess.Popen', side_effect=_make_file_based_piper()):
            path = tts.speak("Hello world")
        assert path is not None, "speak() returned None"
        assert os.path.exists(path), f"speak() returned nonexistent path: {path}"
        with wave.open(path, 'rb') as wf:
            assert wf.getnframes() > 0, "Live synthesis WAV has no audio frames"

    def test_speak_and_play_plays_valid_wav(self, tmp_path):
        """speak_and_play() must pass a valid WAV path to audio.play_file() at call time."""
        import wave
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        valid_wav_paths = []

        original_play_file = audio.play_file

        def intercepting_play_file(path):
            # Capture whether the file is a valid WAV at the moment play_file is called
            try:
                with wave.open(path, 'rb') as wf:
                    valid_wav_paths.append(wf.getnframes())
            except Exception:
                valid_wav_paths.append(0)
            return original_play_file(path)

        audio.play_file = intercepting_play_file

        with patch('subprocess.Popen', side_effect=_make_file_based_piper()):
            tts.speak_and_play("Hello world")

        assert len(valid_wav_paths) == 1, "play_file was not called"
        assert valid_wav_paths[0] > 0, "Played WAV file had no audio frames at call time"

    def test_prerender_then_speak_and_play_uses_valid_cached_wav(self, tmp_path):
        """After prerender, speak_and_play uses the cached WAV; it must be valid."""
        import wave
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        text = "Hello, operator."
        script_name = "SCRIPT_GREETING"

        with patch('subprocess.Popen', side_effect=_make_file_based_piper()):
            tts.prerender({script_name: text})

        # speak_and_play should use cache, no new Piper call
        piper_calls = [0]

        def count_piper(cmd, stdin, stdout, stderr, **kwargs):
            piper_calls[0] += 1
            return _make_file_based_piper()(cmd, stdin, stdout, stderr)

        with patch('subprocess.Popen', side_effect=count_piper):
            tts.speak_and_play(text)

        assert piper_calls[0] == 0, "Piper was called when cached WAV should have been used"
        play_calls = [c for c in audio.calls if c[0] == 'play_file']
        assert len(play_calls) == 1, "play_file was not called"
        with wave.open(play_calls[0][1], 'rb') as wf:
            assert wf.getnframes() > 0, "Cached WAV is not a valid WAV file"

    def test_run_piper_uses_output_file_flag(self, tmp_path):
        """_run_piper must pass --output_file <path> to Piper, not --output-raw."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        observed_cmds = []

        def capture_cmd(cmd, stdin, stdout, stderr, **kwargs):
            observed_cmds.append(list(cmd))
            return _make_file_based_piper()(cmd, stdin, stdout, stderr)

        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            out_path = f.name

        try:
            with patch('subprocess.Popen', side_effect=capture_cmd):
                tts._run_piper("hello", out_path)
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

        assert observed_cmds, "Piper was never called"
        cmd = observed_cmds[0]
        assert '--output_file' in cmd, f"--output_file not in cmd: {cmd}"
        assert '--output-raw' not in cmd, f"--output-raw still present in cmd: {cmd}"


# ---------------------------------------------------------------------------
# TTS temp file cleanup (F-07)
# ---------------------------------------------------------------------------

class TestLiveDirCleanup:
    """PiperTTS must write live-synthesis files to <cache_dir>/live/ and clean
    them up after playback so no orphan WAVs accumulate."""

    def test_init_creates_live_dir(self, tmp_path):
        """PiperTTS.__init__ creates <cache_dir>/live/ if it does not exist."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        live_dir = os.path.join(cache_dir, "live")
        assert os.path.isdir(live_dir), f"live/ dir not created: {live_dir}"

    def test_init_clears_existing_live_files(self, tmp_path):
        """Pre-existing files in <cache_dir>/live/ are removed on __init__."""
        cache_dir = str(tmp_path / "tts_cache")
        live_dir = os.path.join(cache_dir, "live")
        os.makedirs(live_dir, exist_ok=True)
        # Plant a leftover file from a previous session
        leftover = os.path.join(live_dir, "leftover.wav")
        open(leftover, 'wb').close()
        assert os.path.exists(leftover)

        # Instantiating PiperTTS should wipe the directory
        audio = MockAudio()
        eq = MockErrorQueue()
        PiperTTS(
            piper_binary="/fake/piper",
            piper_model="/fake/model.onnx",
            cache_dir=cache_dir,
            audio=audio,
            error_queue=eq,
        )
        assert not os.path.exists(leftover), "Leftover live file was not cleaned on init"

    def test_live_synthesis_file_in_live_dir(self, tmp_path):
        """_synthesize writes temp files inside <cache_dir>/live/, not system /tmp."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        live_dir = os.path.join(cache_dir, "live")
        captured_paths = []

        original_play_file = audio.play_file

        def capturing_play_file(path):
            captured_paths.append(path)
            return original_play_file(path)

        audio.play_file = capturing_play_file

        with patch('subprocess.Popen', side_effect=_make_file_based_piper()):
            tts.speak_and_play("some dynamic text not prerendered")

        assert captured_paths, "play_file was never called"
        played_path = captured_paths[0]
        assert played_path.startswith(live_dir), (
            f"Live synthesis file {played_path!r} is not inside live_dir {live_dir!r}"
        )

    def test_live_file_deleted_after_speak_and_play(self, tmp_path):
        """After speak_and_play completes, the live temp WAV file is removed."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        captured_paths = []

        original_play_file = audio.play_file

        def capturing_play_file(path):
            captured_paths.append(path)
            return original_play_file(path)

        audio.play_file = capturing_play_file

        with patch('subprocess.Popen', side_effect=_make_file_based_piper()):
            tts.speak_and_play("some dynamic text not prerendered")

        assert captured_paths, "play_file was never called"
        played_path = captured_paths[0]
        assert not os.path.exists(played_path), (
            f"Live temp file {played_path!r} was not deleted after speak_and_play"
        )

    def test_prerendered_cache_files_not_deleted(self, tmp_path):
        """speak_and_play for a pre-rendered script must NOT delete the cache file."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        text = "Hello, operator speaking."
        script_name = "SCRIPT_CLEANUP_TEST"

        with patch('subprocess.Popen', side_effect=_make_file_based_piper()):
            tts.prerender({script_name: text})

        wav_path = os.path.join(cache_dir, f"{script_name}.wav")
        assert os.path.exists(wav_path), "Pre-rendered WAV should exist after prerender"

        # Now play the cached script
        with patch('subprocess.Popen', side_effect=_make_file_based_piper()):
            tts.speak_and_play(text)

        assert os.path.exists(wav_path), (
            "Pre-rendered cache WAV was incorrectly deleted after speak_and_play"
        )

    def test_multiple_live_calls_cleanup_all(self, tmp_path):
        """Each live speak_and_play call deletes its own temp file; none accumulate."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        live_dir = os.path.join(cache_dir, "live")
        played_paths = []

        original_play_file = audio.play_file

        def capturing_play_file(path):
            played_paths.append(path)
            return original_play_file(path)

        audio.play_file = capturing_play_file

        with patch('subprocess.Popen', side_effect=_make_file_based_piper()):
            tts.speak_and_play("first dynamic string")
            tts.speak_and_play("second dynamic string")
            tts.speak_and_play("third dynamic string")

        assert len(played_paths) == 3, "Expected 3 play_file calls"
        for path in played_paths:
            assert not os.path.exists(path), f"Temp file {path!r} was not cleaned up"

        # live dir should be empty (no leftover files)
        remaining = os.listdir(live_dir)
        assert remaining == [], f"Live dir has leftover files: {remaining}"

    def test_speak_also_cleans_up(self, tmp_path):
        """speak() (not speak_and_play) must also write to live/ dir."""
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        live_dir = os.path.join(cache_dir, "live")

        with patch('subprocess.Popen', side_effect=_make_file_based_piper()):
            path = tts.speak("some text for speak")

        assert path is not None, "speak() returned None"
        assert path.startswith(live_dir), (
            f"speak() returned path {path!r} not inside live_dir {live_dir!r}"
        )


# ---------------------------------------------------------------------------
# F-22: hash file context manager
# ---------------------------------------------------------------------------

class TestHashFileContextManager:
    """The hash file in prerender() must be read inside a `with` block."""

    def test_prerender_reads_hash_with_context_manager(self):
        """Verify that tts.py uses `with open(...)` to read the hash file."""
        import inspect
        from src.tts import PiperTTS
        source = inspect.getsource(PiperTTS.prerender)
        # The bare `open(hash_path)` call must not appear
        assert "stored_hash = open(" not in source, (
            "prerender() reads the hash file without a context manager "
            "(bare open() call found); use `with open(...) as f:` instead"
        )
        # A context-manager read must be present
        assert "with open(" in source, (
            "prerender() does not use `with open(...)` to read the hash file"
        )


# ---------------------------------------------------------------------------
# F-23: Narrow except Exception in _run_piper()
# ---------------------------------------------------------------------------

class TestNarrowRunPiperException:
    """_run_piper() must catch OSError (not bare except Exception)."""

    def test_run_piper_oserror_returns_false(self, tmp_path):
        """OSError from subprocess.Popen → _run_piper() returns False."""
        from src.tts import PiperTTS
        from src.error_queue import MockErrorQueue
        from src.audio import MockAudio
        from unittest.mock import patch

        eq = MockErrorQueue()
        audio = MockAudio()
        cache_dir = str(tmp_path / "tts_cache")
        tts = PiperTTS(
            piper_binary="/fake/piper",
            piper_model="/fake/model.onnx",
            cache_dir=cache_dir,
            audio=audio,
            error_queue=eq,
        )

        with patch('subprocess.Popen', side_effect=OSError("No such file or directory")):
            result = tts._run_piper("hello", str(tmp_path / "out.wav"))

        assert result is False, f"Expected False when Popen raises OSError; got {result!r}"

    def test_run_piper_oserror_logs_error(self, tmp_path):
        """OSError from subprocess.Popen → error is logged via error_queue."""
        from src.tts import PiperTTS
        from src.error_queue import MockErrorQueue
        from src.audio import MockAudio
        from unittest.mock import patch

        eq = MockErrorQueue()
        audio = MockAudio()
        cache_dir = str(tmp_path / "tts_cache")
        tts = PiperTTS(
            piper_binary="/fake/piper",
            piper_model="/fake/model.onnx",
            cache_dir=cache_dir,
            audio=audio,
            error_queue=eq,
        )

        with patch('subprocess.Popen', side_effect=OSError("No such file or directory")):
            tts.speak_and_play("some text")

        errors = [e for e in eq.entries if e.severity == 'error']
        assert len(errors) >= 1, f"Expected error logged for OSError; entries: {eq.entries}"


# ---------------------------------------------------------------------------
# MockTTS
# ---------------------------------------------------------------------------

class TestMockTTS:

    def test_mock_tts_records_calls(self, tmp_path):
        audio = MockAudio()
        mock = MockTTS(audio=audio)
        path = mock.speak("hello")
        assert path is not None
        mock.speak_and_play("hello")
        mock.speak_digits("123")
        mock.prerender({"GREETING": "hello"})
        assert ('speak', 'hello') in mock.calls
        assert ('speak_and_play', 'hello') in mock.calls
        assert ('speak_digits', '123') in mock.calls
        assert ('prerender', {"GREETING": "hello"}) in mock.calls
