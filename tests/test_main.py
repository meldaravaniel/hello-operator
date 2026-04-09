"""Tests for F-01: constructor argument mismatches in main.py.

Verifies that each concrete class used in main.py accepts the exact
keyword arguments that main.py passes to it. No TypeError should be raised
during object construction.
"""

import pytest
import tempfile
import os


def test_piper_tts_accepts_piper_model_kwarg(mock_audio, mock_error_queue):
    """PiperTTS constructor must accept piper_model= (not model_path=)."""
    from src.tts import PiperTTS

    with tempfile.TemporaryDirectory() as cache_dir:
        # Should not raise TypeError
        tts = PiperTTS(
            piper_binary="/usr/bin/piper",
            piper_model="/path/to/model.onnx",
            cache_dir=cache_dir,
            audio=mock_audio,
            error_queue=mock_error_queue,
        )
        assert tts is not None


def test_plex_client_accepts_url_kwarg():
    """PlexClient constructor must accept url= (not base_url=)."""
    from src.plex_client import PlexClient

    # Should not raise TypeError
    client = PlexClient(url="http://localhost:32400", token="dummy-token")
    assert client is not None


def test_gpio_handler_accepts_pin_reader_kwargs():
    """GPIOHandler constructor must accept hook_pin_reader= and pulse_pin_reader=
    (not hook_reader=, pulse_reader=, hook_debounce=, pulse_debounce=).
    """
    from src.gpio_handler import GPIOHandler

    hook_reader = lambda: 1
    pulse_reader = lambda: 1

    # Should not raise TypeError
    handler = GPIOHandler(
        hook_pin_reader=hook_reader,
        pulse_pin_reader=pulse_reader,
    )
    assert handler is not None


def test_gpio_handler_rejects_old_kwargs():
    """GPIOHandler must NOT accept the old wrong keyword argument names."""
    from src.gpio_handler import GPIOHandler

    with pytest.raises(TypeError):
        GPIOHandler(
            hook_reader=lambda: 1,
            pulse_reader=lambda: 1,
            hook_debounce=0.05,
            pulse_debounce=0.005,
        )


def test_piper_tts_rejects_old_model_path_kwarg(mock_audio, mock_error_queue):
    """PiperTTS must NOT accept model_path= (the old wrong keyword name)."""
    from src.tts import PiperTTS

    with tempfile.TemporaryDirectory() as cache_dir:
        with pytest.raises(TypeError):
            PiperTTS(
                piper_binary="/usr/bin/piper",
                model_path="/path/to/model.onnx",
                cache_dir=cache_dir,
                audio=mock_audio,
                error_queue=mock_error_queue,
            )


def test_plex_client_rejects_old_base_url_kwarg():
    """PlexClient must NOT accept base_url= (the old wrong keyword name)."""
    from src.plex_client import PlexClient

    with pytest.raises(TypeError):
        PlexClient(base_url="http://localhost:32400", token="dummy-token")
