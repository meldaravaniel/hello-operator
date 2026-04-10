"""FM radio playback via RTL-SDR dongle (rtl_fm | aplay pipeline)."""

import shutil
import subprocess

from src.interfaces import RadioInterface


class RtlFmRadio(RadioInterface):
    """Concrete RadioInterface that drives an RTL2832U dongle via rtl_fm and aplay."""

    def __init__(self):
        self._rtl_proc = None
        self._aplay_proc = None

    def play(self, frequency_hz: float) -> None:
        """Tune to frequency_hz and start streaming audio.

        Raises RuntimeError if rtl_fm or aplay are not on PATH.
        """
        if not shutil.which("rtl_fm"):
            raise RuntimeError(
                "rtl_fm not found on PATH — install rtl-sdr to use radio"
            )
        if not shutil.which("aplay"):
            raise RuntimeError(
                "aplay not found on PATH — install alsa-utils to use radio"
            )

        # Stop any previous session first
        self.stop()

        # Open aplay first so we can pipe rtl_fm's stdout into it
        self._aplay_proc = subprocess.Popen(
            ["aplay", "-r", "48k", "-f", "S16_LE", "-t", "raw", "-"],
            stdin=subprocess.PIPE,
        )
        self._rtl_proc = subprocess.Popen(
            ["rtl_fm", "-f", str(int(frequency_hz)), "-M", "fm", "-s", "200k", "-r", "48k", "-"],
            stdout=self._aplay_proc.stdin,
        )

    def stop(self) -> None:
        """Terminate both rtl_fm and aplay processes."""
        for proc in (self._rtl_proc, self._aplay_proc):
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._rtl_proc = None
        self._aplay_proc = None

    def is_playing(self) -> bool:
        """True while the rtl_fm process is still running."""
        return self._rtl_proc is not None and self._rtl_proc.poll() is None


class MockRadio(RadioInterface):
    """Test double for RadioInterface — tracks calls and simulates state."""

    def __init__(self):
        self.calls: list = []
        self._playing: bool = False

    def play(self, frequency_hz: float) -> None:
        """Record the call and set playing state."""
        self.calls.append(('play', frequency_hz))
        self._playing = True

    def stop(self) -> None:
        """Record the call and clear playing state."""
        self.calls.append(('stop',))
        self._playing = False

    def is_playing(self) -> bool:
        """Return the current playing state."""
        return self._playing

    def set_playing(self, value: bool) -> None:
        """Directly set the playing state (for test setup)."""
        self._playing = value
