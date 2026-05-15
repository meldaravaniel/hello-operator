"""Tests for src/audio.py."""

import io
import queue
import subprocess
import threading
import wave
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

from src.audio import (
    SounddeviceAudio, MockAudio, AudioTask,
    _generate_tone, _DTMF_FREQ, _CHUNK_FRAMES, _SAMPLE_RATE,
    _OFF_HOOK_FREQ, _DIAL_TONE_FREQ, _DTMF_DURATION_MS, _WARMUP_MS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wav_bytes(sample_rate=8000, n_samples=100, n_channels=1, sampwidth=2):
    """Return minimal valid WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(np.zeros(n_samples * n_channels, dtype=np.int16).tobytes())
    return buf.getvalue()


def _make_pcm(n_bytes=440):
    """Return n_bytes of zeroed PCM."""
    return bytes(n_bytes)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_amp():
    return MagicMock()


@pytest.fixture
def mock_proc():
    proc = MagicMock()
    proc.poll.return_value = None  # process is running
    proc.stdin = MagicMock()
    return proc


@pytest.fixture
def mock_popen(mock_proc):
    return MagicMock(return_value=mock_proc)


@pytest.fixture
def audio(mock_amp, mock_popen):
    """SounddeviceAudio with worker thread suppressed and subprocess mocked."""
    with patch("src.audio.threading.Thread"):
        return SounddeviceAudio(
            sd_pin_out=mock_amp,
            sample_rate=8000,
            device="hw:test",
            volume=1.0,
            _popen=mock_popen,
        )


@pytest.fixture
def audio_with_proc(audio, mock_proc):
    """audio fixture with _proc pre-set so _write_raw is not a no-op."""
    audio._proc = mock_proc
    return audio


# ---------------------------------------------------------------------------
# _generate_tone
# ---------------------------------------------------------------------------


class TestGenerateTone:
    def test_returns_float32_array(self):
        result = _generate_tone([440], 100)
        assert result.dtype == np.float32

    def test_length_matches_duration(self):
        sr = 8000
        result = _generate_tone([440], 250, sample_rate=sr)
        expected = int(sr * 250 / 1000)
        assert len(result) == expected

    def test_peak_is_normalised_to_one(self):
        result = _generate_tone([440, 880], 100)
        assert np.max(np.abs(result)) == pytest.approx(1.0, abs=1e-5)

    def test_single_frequency(self):
        result = _generate_tone([1000], 50, sample_rate=8000)
        assert result is not None
        assert len(result) > 0

    def test_multiple_frequencies(self):
        result_single = _generate_tone([440], 100, sample_rate=8000)
        result_multi = _generate_tone([440, 880], 100, sample_rate=8000)
        assert len(result_single) == len(result_multi)


# ---------------------------------------------------------------------------
# AudioTask
# ---------------------------------------------------------------------------


class TestAudioTask:
    def test_describe_returns_description(self):
        t = AudioTask("test task", b"\x00")
        assert t.describe() == "test task"

    def test_get_bytes_returns_pcm(self):
        pcm = b"\x01\x02\x03"
        t = AudioTask("x", pcm)
        assert t.getBytes() == pcm

    def test_is_loop_defaults_false(self):
        t = AudioTask("x", b"")
        assert t.isLoop() is False

    def test_is_loop_true_when_set(self):
        t = AudioTask("x", b"", loop=True)
        assert t.isLoop() is True

    def test_is_done_starts_false(self):
        t = AudioTask("x", b"")
        assert t.isDone() is False

    def test_stop_sets_done(self):
        t = AudioTask("x", b"")
        t.stop()
        assert t.isDone() is True

    def test_stop_is_idempotent(self):
        t = AudioTask("x", b"")
        t.stop()
        t.stop()
        assert t.isDone() is True


# ---------------------------------------------------------------------------
# SounddeviceAudio.__init__
# ---------------------------------------------------------------------------


class TestSounddeviceAudioInit:
    def test_stores_sample_rate(self, audio):
        assert audio._sample_rate == 8000

    def test_stores_device(self, audio):
        assert audio._device == "hw:test"

    def test_stores_volume_at_one(self, audio):
        assert audio._volume == 1.0

    def test_clamps_volume_above_one(self, mock_amp, mock_popen):
        with patch("src.audio.threading.Thread"):
            a = SounddeviceAudio(mock_amp, volume=1.5, _popen=mock_popen)
        assert a._volume == 1.0

    def test_clamps_volume_below_zero(self, mock_amp, mock_popen):
        with patch("src.audio.threading.Thread"):
            a = SounddeviceAudio(mock_amp, volume=-0.5, _popen=mock_popen)
        assert a._volume == 0.0

    def test_uses_provided_popen(self, audio, mock_popen):
        assert audio._popen is mock_popen

    def test_defaults_popen_to_subprocess(self, mock_amp):
        with patch("src.audio.threading.Thread"):
            a = SounddeviceAudio(mock_amp)
        assert a._popen is subprocess.Popen

    def test_busy_starts_false(self, audio):
        assert audio._busy is False

    def test_proc_starts_none(self, audio):
        assert audio._proc is None

    def test_current_task_starts_none(self, audio):
        assert audio._current_task is None

    def test_queue_starts_empty(self, audio):
        assert audio._queue.empty()

    def test_worker_thread_started(self, mock_amp, mock_popen):
        with patch("src.audio.threading.Thread") as MockThread:
            SounddeviceAudio(mock_amp, _popen=mock_popen)
        MockThread.return_value.start.assert_called_once()

    def test_worker_thread_is_daemon(self, mock_amp, mock_popen):
        with patch("src.audio.threading.Thread") as MockThread:
            SounddeviceAudio(mock_amp, _popen=mock_popen)
        _, kwargs = MockThread.call_args
        assert kwargs.get("daemon") is True

    def test_worker_thread_target_is_worker_loop(self, mock_amp, mock_popen):
        with patch("src.audio.threading.Thread") as MockThread:
            a = SounddeviceAudio(mock_amp, _popen=mock_popen)
        _, kwargs = MockThread.call_args
        assert kwargs.get("target") == a._worker_loop


# ---------------------------------------------------------------------------
# amp_on
# ---------------------------------------------------------------------------


class TestAmpOn:
    def test_starts_aplay_when_no_process(self, audio, mock_popen):
        audio.amp_on()
        mock_popen.assert_called_once()

    def test_aplay_command_includes_device(self, audio, mock_popen):
        audio.amp_on()
        args, _ = mock_popen.call_args
        assert "hw:test" in args[0]

    def test_aplay_command_includes_sample_rate(self, audio, mock_popen):
        audio.amp_on()
        args, _ = mock_popen.call_args
        assert "8000" in args[0]

    def test_aplay_command_starts_with_aplay(self, audio, mock_popen):
        audio.amp_on()
        args, _ = mock_popen.call_args
        assert args[0][0] == "aplay"

    def test_aplay_stdin_is_pipe(self, audio, mock_popen):
        audio.amp_on()
        _, kwargs = mock_popen.call_args
        assert kwargs["stdin"] == subprocess.PIPE

    def test_writes_warmup_silence_to_stdin(self, audio, mock_proc):
        audio.amp_on()
        mock_proc.stdin.write.assert_called_once()
        written = mock_proc.stdin.write.call_args[0][0]
        expected_frames = int(8000 * _WARMUP_MS / 1000)
        assert len(written) == expected_frames * 2  # int16 = 2 bytes

    def test_enables_amp(self, audio, mock_amp):
        audio.amp_on()
        mock_amp.on.assert_called_once()

    def test_does_not_restart_running_process(self, audio, mock_popen, mock_proc):
        audio._proc = mock_proc
        mock_proc.poll.return_value = None  # still running
        audio.amp_on()
        mock_popen.assert_not_called()

    def test_restarts_dead_process(self, audio, mock_popen, mock_proc):
        audio._proc = mock_proc
        mock_proc.poll.return_value = 1  # process exited
        audio.amp_on()
        mock_popen.assert_called_once()

    def test_still_enables_amp_when_process_already_running(
            self, audio, mock_amp, mock_proc):
        audio._proc = mock_proc
        mock_proc.poll.return_value = None
        audio.amp_on()
        mock_amp.on.assert_called_once()

    def test_handles_broken_pipe_on_warmup_write(self, audio, mock_proc):
        mock_proc.stdin.write.side_effect = BrokenPipeError
        audio.amp_on()  # must not raise


# ---------------------------------------------------------------------------
# amp_off
# ---------------------------------------------------------------------------


class TestAmpOff:
    def test_disables_amp(self, audio, mock_amp):
        audio.amp_off()
        mock_amp.off.assert_called_once()

    def test_terminates_process(self, audio, mock_proc):
        audio._proc = mock_proc
        audio.amp_off()
        mock_proc.terminate.assert_called_once()

    def test_sets_proc_to_none(self, audio, mock_proc):
        audio._proc = mock_proc
        audio.amp_off()
        assert audio._proc is None

    def test_drains_queue(self, audio):
        audio._queue.put(AudioTask("x", b""))
        audio._queue.put(AudioTask("y", b""))
        audio.amp_off()
        assert audio._queue.empty()

    def test_no_terminate_when_proc_is_none(self, audio):
        audio._proc = None
        audio.amp_off()  # must not raise

    def test_handles_oserror_on_terminate(self, audio, mock_proc):
        audio._proc = mock_proc
        mock_proc.terminate.side_effect = OSError("already dead")
        audio.amp_off()  # must not raise


# ---------------------------------------------------------------------------
# play_tone
# ---------------------------------------------------------------------------


class TestPlayTone:
    def test_enqueues_one_task(self, audio):
        audio.play_tone([440], 100)
        assert audio._queue.qsize() == 1

    def test_task_is_not_looping(self, audio):
        audio.play_tone([440], 100)
        task = audio._queue.get_nowait()
        assert task.isLoop() is False

    def test_task_description_mentions_frequencies(self, audio):
        audio.play_tone([440, 880], 100)
        task = audio._queue.get_nowait()
        assert "440" in task.describe()

    def test_pcm_is_non_empty(self, audio):
        audio.play_tone([440], 100)
        task = audio._queue.get_nowait()
        assert len(task.getBytes()) > 0

    def test_returns_immediately(self, audio):
        # Should not block even without a worker
        audio.play_tone([440], 100)


# ---------------------------------------------------------------------------
# play_file
# ---------------------------------------------------------------------------


class TestPlayFile:
    def test_enqueues_one_task(self, audio, tmp_path):
        wav = tmp_path / "clip.wav"
        wav.write_bytes(_make_wav_bytes())
        audio.play_file(str(wav))
        assert audio._queue.qsize() == 1

    def test_task_description_contains_path(self, audio, tmp_path):
        wav = tmp_path / "clip.wav"
        wav.write_bytes(_make_wav_bytes())
        audio.play_file(str(wav))
        task = audio._queue.get_nowait()
        assert str(wav) in task.describe()

    def test_task_is_not_looping(self, audio, tmp_path):
        wav = tmp_path / "clip.wav"
        wav.write_bytes(_make_wav_bytes())
        audio.play_file(str(wav))
        task = audio._queue.get_nowait()
        assert task.isLoop() is False

    def test_pcm_is_non_empty(self, audio, tmp_path):
        wav = tmp_path / "clip.wav"
        wav.write_bytes(_make_wav_bytes(n_samples=200))
        audio.play_file(str(wav))
        task = audio._queue.get_nowait()
        assert len(task.getBytes()) > 0


# ---------------------------------------------------------------------------
# play_dtmf
# ---------------------------------------------------------------------------


class TestPlayDtmf:
    @pytest.mark.parametrize("digit", range(10))
    def test_enqueues_task_for_each_digit(self, audio, digit):
        audio.play_dtmf(digit)
        assert audio._queue.qsize() == 1

    def test_uses_correct_dtmf_frequencies_for_digit_0(self, audio):
        with patch.object(audio, "play_tone") as mock_play:
            audio.play_dtmf(0)
        freqs, duration = mock_play.call_args[0]
        assert set(freqs) == set(_DTMF_FREQ[0])

    def test_uses_correct_dtmf_frequencies_for_digit_5(self, audio):
        with patch.object(audio, "play_tone") as mock_play:
            audio.play_dtmf(5)
        freqs, duration = mock_play.call_args[0]
        assert set(freqs) == set(_DTMF_FREQ[5])

    def test_uses_dtmf_duration(self, audio):
        with patch.object(audio, "play_tone") as mock_play:
            audio.play_dtmf(1)
        _, duration = mock_play.call_args[0]
        assert duration == _DTMF_DURATION_MS


# ---------------------------------------------------------------------------
# play_off_hook_tone
# ---------------------------------------------------------------------------


class TestPlayOffHookTone:
    def test_enqueues_one_task(self, audio):
        audio.play_off_hook_tone()
        assert audio._queue.qsize() == 1

    def test_task_is_looping(self, audio):
        audio.play_off_hook_tone()
        task = audio._queue.get_nowait()
        assert task.isLoop() is True

    def test_pcm_is_non_empty(self, audio):
        audio.play_off_hook_tone()
        task = audio._queue.get_nowait()
        assert len(task.getBytes()) > 0


# ---------------------------------------------------------------------------
# play_dial_tone
# ---------------------------------------------------------------------------


class TestPlayDialTone:
    def test_enqueues_one_task(self, audio):
        audio.play_dial_tone()
        assert audio._queue.qsize() == 1

    def test_task_is_not_looping(self, audio):
        audio.play_dial_tone()
        task = audio._queue.get_nowait()
        assert task.isLoop() is False

    def test_pcm_is_non_empty(self, audio):
        audio.play_dial_tone()
        task = audio._queue.get_nowait()
        assert len(task.getBytes()) > 0


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


class TestStop:
    def test_drains_single_queued_task(self, audio):
        audio._queue.put(AudioTask("x", b""))
        audio.stop()
        assert audio._queue.empty()

    def test_drains_multiple_queued_tasks(self, audio):
        for _ in range(5):
            audio._queue.put(AudioTask("x", b""))
        audio.stop()
        assert audio._queue.empty()

    def test_sets_busy_false(self, audio):
        audio._busy = True
        audio.stop()
        assert audio._busy is False

    def test_stops_current_task_if_present(self, audio):
        task = AudioTask("current", b"")
        audio._current_task = task
        audio.stop()
        assert task.isDone() is True

    def test_no_error_when_current_task_is_none(self, audio):
        audio._current_task = None
        audio.stop()  # must not raise

    def test_no_error_on_empty_queue(self, audio):
        audio.stop()  # must not raise


# ---------------------------------------------------------------------------
# is_playing
# ---------------------------------------------------------------------------


class TestIsPlaying:
    def test_false_when_idle(self, audio):
        assert audio.is_playing() is False

    def test_true_when_busy(self, audio):
        audio._busy = True
        assert audio.is_playing() is True

    def test_true_when_queue_non_empty(self, audio):
        audio._queue.put(AudioTask("x", b""))
        assert audio.is_playing() is True

    def test_false_after_stop(self, audio):
        audio._queue.put(AudioTask("x", b""))
        audio._busy = True
        audio.stop()
        assert audio.is_playing() is False


# ---------------------------------------------------------------------------
# _enqueue
# ---------------------------------------------------------------------------


class TestEnqueue:
    def test_puts_task_in_queue(self, audio):
        task = AudioTask("x", b"")
        audio._enqueue(task)
        assert audio._queue.qsize() == 1

    def test_the_enqueued_task_is_retrievable(self, audio):
        task = AudioTask("x", b"")
        audio._enqueue(task)
        assert audio._queue.get_nowait() is task

    def test_stops_current_task_when_present(self, audio):
        current = AudioTask("current", b"")
        audio._current_task = current
        audio._enqueue(AudioTask("new", b""))
        assert current.isDone() is True

    def test_no_error_when_no_current_task(self, audio):
        audio._current_task = None
        audio._enqueue(AudioTask("x", b""))  # must not raise


# ---------------------------------------------------------------------------
# _write_pcm
# ---------------------------------------------------------------------------


class TestWritePcm:
    def test_writes_all_bytes_in_one_chunk(self, audio_with_proc):
        pcm = _make_pcm(_CHUNK_FRAMES * 2)  # exactly one chunk
        task = AudioTask("t", pcm)
        audio_with_proc._write_pcm(task)
        audio_with_proc._proc.stdin.write.assert_called_once()

    def test_writes_multiple_chunks_for_large_pcm(self, audio_with_proc):
        pcm = _make_pcm(_CHUNK_FRAMES * 2 * 3)  # three chunks
        task = AudioTask("t", pcm)
        audio_with_proc._write_pcm(task)
        assert audio_with_proc._proc.stdin.write.call_count == 3

    def test_stops_early_when_task_is_done(self, audio_with_proc):
        pcm = _make_pcm(_CHUNK_FRAMES * 2 * 4)  # four chunks
        task = AudioTask("t", pcm)

        call_count = [0]

        def stop_after_one(data):
            call_count[0] += 1
            if call_count[0] >= 1:
                task.stop()

        audio_with_proc._write_raw = stop_after_one
        audio_with_proc._write_pcm(task)
        assert call_count[0] == 1

    def test_no_op_when_proc_is_none(self, audio):
        audio._proc = None
        pcm = _make_pcm(_CHUNK_FRAMES * 2)
        task = AudioTask("t", pcm)
        audio._write_pcm(task)  # must not raise


# ---------------------------------------------------------------------------
# _write_pcm_loop
# ---------------------------------------------------------------------------


class TestWritePcmLoop:
    def test_loops_until_task_stopped(self, audio_with_proc):
        pcm = _make_pcm(_CHUNK_FRAMES * 2)  # one chunk
        task = AudioTask("t", pcm, loop=True)

        call_count = [0]

        def stop_after_three(data):
            call_count[0] += 1
            if call_count[0] >= 3:
                task.stop()

        audio_with_proc._write_raw = stop_after_three
        audio_with_proc._write_pcm_loop(task)
        assert call_count[0] == 3

    def test_wraps_around_when_pcm_exhausted(self, audio_with_proc):
        pcm = _make_pcm(_CHUNK_FRAMES * 2)  # one chunk per wrap
        task = AudioTask("t", pcm, loop=True)

        written_slices = []

        def record_then_stop(data):
            written_slices.append(data)
            if len(written_slices) >= 4:
                task.stop()

        audio_with_proc._write_raw = record_then_stop
        audio_with_proc._write_pcm_loop(task)
        assert len(written_slices) >= 2  # wrapped at least once

    def test_exits_immediately_if_already_stopped(self, audio_with_proc):
        pcm = _make_pcm(_CHUNK_FRAMES * 2)
        task = AudioTask("t", pcm, loop=True)
        task.stop()

        call_count = [0]

        def record(data):
            call_count[0] += 1

        audio_with_proc._write_raw = record
        audio_with_proc._write_pcm_loop(task)
        assert call_count[0] == 0


# ---------------------------------------------------------------------------
# _waveform_to_pcm
# ---------------------------------------------------------------------------


class TestWaveformToPcm:
    def test_returns_bytes(self, audio):
        wf = np.zeros(100, dtype=np.float32)
        assert isinstance(audio._waveform_to_pcm(wf), bytes)

    def test_length_is_two_bytes_per_sample(self, audio):
        wf = np.zeros(50, dtype=np.float32)
        assert len(audio._waveform_to_pcm(wf)) == 100  # 50 * 2

    def test_full_scale_maps_to_near_max_int16(self, audio):
        wf = np.ones(1, dtype=np.float32)
        pcm = audio._waveform_to_pcm(wf)
        value = np.frombuffer(pcm, dtype=np.int16)[0]
        assert value == pytest.approx(32767, abs=1)

    def test_volume_scales_amplitude(self, mock_amp, mock_popen):
        with patch("src.audio.threading.Thread"):
            a = SounddeviceAudio(mock_amp, sample_rate=8000, volume=0.5, _popen=mock_popen)
        wf = np.ones(1, dtype=np.float32)
        pcm = a._waveform_to_pcm(wf)
        value = np.frombuffer(pcm, dtype=np.int16)[0]
        assert value == pytest.approx(int(32767 * 0.5), abs=2)

    def test_clips_values_above_one(self, audio):
        wf = np.array([2.0], dtype=np.float32)
        pcm = audio._waveform_to_pcm(wf)
        value = np.frombuffer(pcm, dtype=np.int16)[0]
        assert value == pytest.approx(32767, abs=1)

    def test_zero_waveform_produces_silence(self, audio):
        wf = np.zeros(10, dtype=np.float32)
        pcm = audio._waveform_to_pcm(wf)
        assert all(b == 0 for b in pcm)


# ---------------------------------------------------------------------------
# _wav_to_pcm
# ---------------------------------------------------------------------------


class TestWavToPcm:
    def test_returns_bytes(self, audio):
        result = audio._wav_to_pcm(_make_wav_bytes())
        assert isinstance(result, bytes)

    def test_non_empty_output(self, audio):
        result = audio._wav_to_pcm(_make_wav_bytes(n_samples=100))
        assert len(result) > 0

    def test_mono_passthrough(self, audio):
        wav = _make_wav_bytes(sample_rate=8000, n_samples=100, n_channels=1)
        result = audio._wav_to_pcm(wav)
        assert len(result) == 100 * 2  # 100 samples * 2 bytes each

    def test_stereo_downmix_to_mono(self, audio):
        wav = _make_wav_bytes(sample_rate=8000, n_samples=100, n_channels=2)
        result = audio._wav_to_pcm(wav)
        # After downmix: 100 mono samples * 2 bytes
        assert len(result) == 100 * 2

    def test_resampling_changes_output_length(self, audio):
        # Source at 4000 Hz, target at 8000 Hz → 2× upsampling
        wav = _make_wav_bytes(sample_rate=4000, n_samples=100)
        result = audio._wav_to_pcm(wav)
        # Output should be approximately 200 samples * 2 bytes
        assert len(result) == pytest.approx(200 * 2, abs=4)

    def test_volume_applied_to_wav_output(self, mock_amp, mock_popen):
        with patch("src.audio.threading.Thread"):
            a = SounddeviceAudio(mock_amp, sample_rate=8000, volume=0.0, _popen=mock_popen)
        # At volume=0.0, every sample is 0
        wav = _make_wav_bytes(n_samples=10)
        result = a._wav_to_pcm(wav)
        assert all(b == 0 for b in result)


# ---------------------------------------------------------------------------
# MockAudio
# ---------------------------------------------------------------------------


class TestMockAudio:
    def test_can_be_instantiated(self):
        m = MockAudio()
        assert m is not None

    def test_calls_starts_empty(self):
        m = MockAudio()
        assert m.calls == []

    def test_is_playing_starts_false(self):
        m = MockAudio()
        assert m.is_playing() is False

    def test_play_tone_records_call(self):
        m = MockAudio()
        m.play_tone([440], 150)
        assert ('play_tone', [440], 150) in m.calls

    def test_play_tone_sets_playing(self):
        m = MockAudio()
        m.play_tone([440], 150)
        assert m.is_playing() is True

    def test_play_file_records_call(self):
        m = MockAudio()
        m.play_file("/tmp/clip.wav")
        assert ('play_file', "/tmp/clip.wav") in m.calls

    def test_play_file_sets_playing(self):
        m = MockAudio()
        m.play_file("/tmp/clip.wav")
        assert m.is_playing() is True

    def test_play_dtmf_records_call(self):
        m = MockAudio()
        m.play_dtmf(5)
        assert ('play_dtmf', 5) in m.calls

    def test_play_dtmf_sets_playing(self):
        m = MockAudio()
        m.play_dtmf(5)
        assert m.is_playing() is True

    def test_play_off_hook_tone_records_call(self):
        m = MockAudio()
        m.play_off_hook_tone()
        assert ('play_off_hook_tone',) in m.calls

    def test_play_off_hook_tone_sets_playing(self):
        m = MockAudio()
        m.play_off_hook_tone()
        assert m.is_playing() is True

    def test_play_dial_tone_records_call(self):
        m = MockAudio()
        m.play_dial_tone()
        assert ('play_dial_tone',) in m.calls

    def test_play_dial_tone_sets_playing(self):
        m = MockAudio()
        m.play_dial_tone()
        assert m.is_playing() is True

    def test_stop_records_call(self):
        m = MockAudio()
        m.stop()
        assert ('stop',) in m.calls

    def test_stop_clears_playing(self):
        m = MockAudio()
        m.play_tone([440], 100)
        m.stop()
        assert m.is_playing() is False

    def test_multiple_calls_all_recorded(self):
        m = MockAudio()
        m.play_tone([440], 100)
        m.play_file("/x.wav")
        m.stop()
        assert len(m.calls) == 3
