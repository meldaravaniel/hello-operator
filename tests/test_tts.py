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
    Return a callable that acts as a fake Piper subprocess: writes a non-empty
    WAV file to the path that would be determined by PiperTTS for the given text.
    """
    def fake_piper(cmd, stdin, stdout, stderr, **kwargs):
        # Write a tiny WAV to stdout that PiperTTS will capture
        import wave, array, io
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            samples = array.array('h', [100] * 2205)
            wf.writeframes(samples.tobytes())
        wav_bytes = buf.getvalue()
        proc = MagicMock()
        proc.communicate.return_value = (wav_bytes, b'')
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
        assert len(play_calls) == 1
        assert os.path.exists(play_calls[0][1])

    def test_speak_digits_individual(self, tmp_path):
        tts, audio, eq, cache_dir = make_tts(tmp_path)
        spoken_texts = []

        def capture_piper(cmd, stdin, stdout, stderr, **kwargs):
            # Extract text from stdin and record it
            import io, wave, array
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(22050)
                samples = array.array('h', [100] * 2205)
                wf.writeframes(samples.tobytes())
            proc = MagicMock()
            proc.communicate.return_value = (buf.getvalue(), b'')
            proc.returncode = 0
            # Record what was passed as stdin input
            spoken_texts.append(cmd)
            return proc

        with patch('subprocess.Popen', side_effect=capture_piper):
            tts.speak_digits("5551234")

        # The spoken text should map each digit to its word
        full_text = " ".join(str(c) for c in spoken_texts)
        for word in ['five', 'one', 'two', 'three', 'four']:
            assert word in full_text.lower() or any(
                word in str(c).lower() for c in spoken_texts
            ), f"'{word}' not found in spoken text: {spoken_texts}"


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

        assert fail_count[0] == CACHE_RETRY_MAX

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
