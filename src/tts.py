"""TTS implementation for hello-operator.

PiperTTS — concrete implementation wrapping the Piper binary.
MockTTS   — records all calls for use in unit tests.

Pre-rendering
-------------
At startup, main.py calls prerender({script_name: text}) with all fixed menu
prompt strings.  prerender() stores a WAV file and a MD5 hash of the source
text for each script.  On subsequent calls, scripts whose hash matches and
whose WAV file exists are skipped (no re-synthesis).

Cache-miss handling
-------------------
If a cached WAV is missing at speak_and_play time:
  1. Log a warning to the error queue.
  2. Attempt to repopulate (re-synthesize) up to CACHE_RETRY_MAX times with
     CACHE_RETRY_BACKOFF seconds between attempts.
  3. If repopulation succeeds, play the newly synthesized file.
  4. If all retries fail, log a persistent error and fall back to live synthesis.

Piper failure
-------------
If Piper fails during live synthesis, log an error and play the off-hook tone.
"""

import hashlib
import os
import subprocess
import time
from typing import Optional

from src.constants import (
    CACHE_RETRY_MAX,
    CACHE_RETRY_BACKOFF,
)
from src.interfaces import AudioInterface, TTSInterface, ErrorQueueInterface

# Mapping from digit character to English word
_DIGIT_WORDS = {
    '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
    '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
}

_SOURCE = "tts"


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


class PiperTTS(TTSInterface):
    """Concrete TTS implementation wrapping the Piper offline binary."""

    def __init__(
        self,
        piper_binary: str,
        piper_model: str,
        cache_dir: str,
        audio: AudioInterface,
        error_queue: ErrorQueueInterface,
    ) -> None:
        self._binary = piper_binary
        self._model = piper_model
        self._cache_dir = cache_dir
        self._audio = audio
        self._error_queue = error_queue
        # Map from normalized text → script_name (populated by prerender)
        self._text_to_script: dict[str, str] = {}
        os.makedirs(cache_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # TTSInterface
    # ------------------------------------------------------------------

    def speak(self, text: str) -> Optional[str]:
        """Synthesize text via Piper; return path to WAV file or None on failure."""
        return self._synthesize(text)

    def speak_and_play(self, text: str) -> None:
        """Synthesize (or use cache) and play via AudioInterface."""
        # Check if this text was pre-rendered
        script_name = self._text_to_script.get(text)
        if script_name is not None:
            wav_path = self._wav_path(script_name)
            if os.path.exists(wav_path):
                self._audio.play_file(wav_path)
                return
            # Cache miss
            self._error_queue.log(_SOURCE, "warning", f"Cache miss for {script_name}")
            # Attempt repopulation
            repopulated = self._repopulate(script_name, text)
            if repopulated:
                self._audio.play_file(self._wav_path(script_name))
                return
            # Fall back to live synthesis
            path = self._synthesize(text)
            if path:
                self._audio.play_file(path)
            return

        # Not a pre-rendered script — live synthesis
        path = self._synthesize(text)
        if path:
            self._audio.play_file(path)

    def speak_digits(self, digits: str) -> None:
        """Speak each digit character individually."""
        words = " ".join(_DIGIT_WORDS.get(c, c) for c in digits)
        self.speak_and_play(words)

    def prerender(self, prompts: dict) -> None:
        """Pre-synthesize fixed strings to cached audio files.

        prompts: {script_name: text}
        """
        for script_name, text in prompts.items():
            wav_path = self._wav_path(script_name)
            hash_path = self._hash_path(script_name)
            current_hash = _md5(text)

            # Check if we can skip
            if os.path.exists(wav_path) and os.path.exists(hash_path):
                stored_hash = open(hash_path).read().strip()
                if stored_hash == current_hash:
                    # Up to date — register and skip
                    self._text_to_script[text] = script_name
                    continue

            # Synthesize
            wav_bytes = self._run_piper(text)
            if wav_bytes:
                with open(wav_path, 'wb') as f:
                    f.write(wav_bytes)
                with open(hash_path, 'w') as f:
                    f.write(current_hash)

            self._text_to_script[text] = script_name

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _wav_path(self, script_name: str) -> str:
        return os.path.join(self._cache_dir, f"{script_name}.wav")

    def _hash_path(self, script_name: str) -> str:
        return os.path.join(self._cache_dir, f"{script_name}.hash")

    def _run_piper(self, text: str) -> Optional[bytes]:
        """Invoke Piper; return WAV bytes or None on failure."""
        cmd = [self._binary, "--model", self._model, "--output-raw"]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = proc.communicate(input=text.encode())
            if proc.returncode != 0 or not stdout:
                return None
            return stdout
        except Exception:
            return None

    def _synthesize(self, text: str) -> Optional[str]:
        """Run Piper live and write output to a temp file. Returns path or None."""
        import tempfile
        wav_bytes = self._run_piper(text)
        if not wav_bytes:
            self._error_queue.log(_SOURCE, "error", f"Piper synthesis failed for: {text[:80]}")
            self._audio.play_off_hook_tone()
            return None
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(wav_bytes)
        except Exception:
            return None
        return path

    def _repopulate(self, script_name: str, text: str) -> bool:
        """Attempt to re-synthesize a cache entry. Returns True on success."""
        for attempt in range(CACHE_RETRY_MAX):
            if attempt > 0:
                time.sleep(CACHE_RETRY_BACKOFF)
            wav_bytes = self._run_piper(text)
            if wav_bytes:
                wav_path = self._wav_path(script_name)
                with open(wav_path, 'wb') as f:
                    f.write(wav_bytes)
                return True
        # All retries exhausted
        self._error_queue.log(_SOURCE, "error", f"Cache repopulation exhausted for {script_name}")
        return False


class MockTTS(TTSInterface):
    """Records all calls; returns canned paths. Used in all unit tests."""

    def __init__(self, audio: Optional[AudioInterface] = None) -> None:
        self.calls: list = []
        self._audio = audio

    def speak(self, text: str) -> str:
        self.calls.append(('speak', text))
        return f"/tmp/mock_tts_{hash(text)}.wav"

    def speak_and_play(self, text: str) -> None:
        self.calls.append(('speak_and_play', text))

    def speak_digits(self, digits: str) -> None:
        self.calls.append(('speak_digits', digits))

    def prerender(self, prompts: dict) -> None:
        self.calls.append(('prerender', prompts))
