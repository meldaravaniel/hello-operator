"""Tests for main.py: constructor argument mismatches (F-01) and startup
directory creation (F-03).

F-01: Verifies that each concrete class used in main.py accepts the exact
keyword arguments that main.py passes to it. No TypeError should be raised
during object construction.

F-03: Verifies that run() creates the database directory before instantiating
any SQLite-backed classes, so startup does not raise OperationalError on a
fresh system.
"""

import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock, call


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


# ---------------------------------------------------------------------------
# F-03: Database directory creation on startup
# ---------------------------------------------------------------------------

def _run_with_stubs(makedirs_mock=None):
    """Run main.run() with all heavy dependencies stubbed out.

    Stops the event loop immediately via KeyboardInterrupt from time.sleep.
    If makedirs_mock is None, os.makedirs is left unpatched.
    Returns the makedirs mock used (or None).
    """
    import src.main as main_mod

    patches = [
        patch("src.main.SqliteErrorQueue", MagicMock()),
        patch("src.main.PhoneBook", MagicMock()),
        patch("src.main.SounddeviceAudio", MagicMock()),
        patch("src.main.PiperTTS", MagicMock()),
        patch("src.main.PlexClient", MagicMock()),
        patch("src.main.PlexStore", MagicMock()),
        patch("src.main.build_gpio_handler", MagicMock()),
        patch("src.main.Session", MagicMock()),
        patch("src.main.time.sleep", side_effect=KeyboardInterrupt),
    ]
    if makedirs_mock is not None:
        patches.append(patch("src.main.os.makedirs", makedirs_mock))

    ctx = [p.__enter__() for p in patches]
    try:
        try:
            main_mod.run()
        except KeyboardInterrupt:
            pass
    finally:
        for p in reversed(patches):
            p.__exit__(None, None, None)

    return makedirs_mock


def test_run_calls_makedirs_before_db_instantiation():
    """run() must call os.makedirs(_DB_DIR, exist_ok=True) before
    instantiating SqliteErrorQueue, PhoneBook, or PlexStore."""
    from src.main import _DB_DIR

    makedirs_mock = MagicMock()
    _run_with_stubs(makedirs_mock=makedirs_mock)

    makedirs_mock.assert_called_once_with(_DB_DIR, exist_ok=True)


def test_run_makedirs_called_before_sqlite_error_queue():
    """makedirs must be called before SqliteErrorQueue is instantiated."""
    from src.main import _DB_DIR

    call_order = []

    makedirs_mock = MagicMock(side_effect=lambda *a, **kw: call_order.append("makedirs"))
    error_queue_mock = MagicMock(side_effect=lambda **kw: call_order.append("SqliteErrorQueue") or MagicMock())

    import src.main as main_mod

    with patch("src.main.os.makedirs", makedirs_mock), \
         patch("src.main.SqliteErrorQueue", error_queue_mock), \
         patch("src.main.PhoneBook", MagicMock()), \
         patch("src.main.SounddeviceAudio", MagicMock()), \
         patch("src.main.PiperTTS", MagicMock()), \
         patch("src.main.PlexClient", MagicMock()), \
         patch("src.main.PlexStore", MagicMock()), \
         patch("src.main.build_gpio_handler", MagicMock()), \
         patch("src.main.Session", MagicMock()), \
         patch("src.main.time.sleep", side_effect=KeyboardInterrupt):
        try:
            main_mod.run()
        except KeyboardInterrupt:
            pass

    assert "makedirs" in call_order, "makedirs was never called"
    assert "SqliteErrorQueue" in call_order, "SqliteErrorQueue was never called"
    assert call_order.index("makedirs") < call_order.index("SqliteErrorQueue"), (
        "makedirs must be called before SqliteErrorQueue"
    )


def test_run_makedirs_exist_ok_true():
    """run() must pass exist_ok=True to os.makedirs so an existing directory
    does not cause an error."""
    from src.main import _DB_DIR

    makedirs_mock = MagicMock()

    import src.main as main_mod

    with patch("src.main.os.makedirs", makedirs_mock), \
         patch("src.main.SqliteErrorQueue", MagicMock()), \
         patch("src.main.PhoneBook", MagicMock()), \
         patch("src.main.SounddeviceAudio", MagicMock()), \
         patch("src.main.PiperTTS", MagicMock()), \
         patch("src.main.PlexClient", MagicMock()), \
         patch("src.main.PlexStore", MagicMock()), \
         patch("src.main.build_gpio_handler", MagicMock()), \
         patch("src.main.Session", MagicMock()), \
         patch("src.main.time.sleep", side_effect=KeyboardInterrupt):
        try:
            main_mod.run()
        except KeyboardInterrupt:
            pass

    makedirs_mock.assert_called_with(_DB_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# F-18: GPIO.cleanup() called on clean shutdown
# ---------------------------------------------------------------------------

def _run_with_gpio_cleanup_mock(gpio_cleanup_mock, build_gpio_raises=False):
    """Run main.run() with all heavy dependencies stubbed out, capturing
    GPIO.cleanup() calls via the provided mock.

    If build_gpio_raises is True, build_gpio_handler() raises ImportError
    (simulating a missing RPi.GPIO module).
    """
    import src.main as main_mod

    if build_gpio_raises:
        build_gpio_side_effect = ImportError("No module named 'RPi'")
    else:
        build_gpio_side_effect = None

    with patch("src.main.os.makedirs", MagicMock()), \
         patch("src.main.SqliteErrorQueue", MagicMock()), \
         patch("src.main.PhoneBook", MagicMock()), \
         patch("src.main.SounddeviceAudio", MagicMock()), \
         patch("src.main.PiperTTS", MagicMock()), \
         patch("src.main.PlexClient", MagicMock()), \
         patch("src.main.PlexStore", MagicMock()), \
         patch("src.main.build_gpio_handler",
               MagicMock(side_effect=build_gpio_side_effect)), \
         patch("src.main.Session", MagicMock()), \
         patch("src.main.time.sleep", side_effect=KeyboardInterrupt), \
         patch("src.main._gpio_cleanup", gpio_cleanup_mock):
        try:
            main_mod.run()
        except (KeyboardInterrupt, ImportError):
            pass


def test_gpio_cleanup_called_on_keyboard_interrupt():
    """run() must call _gpio_cleanup() in the finally block when
    build_gpio_handler() succeeds."""
    gpio_cleanup_mock = MagicMock()
    _run_with_gpio_cleanup_mock(gpio_cleanup_mock, build_gpio_raises=False)
    gpio_cleanup_mock.assert_called_once()


def test_gpio_cleanup_not_called_when_build_raises():
    """run() must NOT call _gpio_cleanup() if build_gpio_handler() raised
    (i.e., GPIO was never initialised)."""
    gpio_cleanup_mock = MagicMock()
    _run_with_gpio_cleanup_mock(gpio_cleanup_mock, build_gpio_raises=True)
    gpio_cleanup_mock.assert_not_called()


def test_gpio_cleanup_called_after_audio_stop():
    """GPIO.cleanup() must be called after audio.stop() in the finally block."""
    import src.main as main_mod

    call_order = []

    audio_mock_instance = MagicMock()
    audio_mock_instance.stop.side_effect = lambda: call_order.append("audio.stop")
    audio_class_mock = MagicMock(return_value=audio_mock_instance)

    gpio_cleanup_mock = MagicMock(side_effect=lambda: call_order.append("gpio_cleanup"))

    with patch("src.main.os.makedirs", MagicMock()), \
         patch("src.main.SqliteErrorQueue", MagicMock()), \
         patch("src.main.PhoneBook", MagicMock()), \
         patch("src.main.SounddeviceAudio", audio_class_mock), \
         patch("src.main.PiperTTS", MagicMock()), \
         patch("src.main.PlexClient", MagicMock()), \
         patch("src.main.PlexStore", MagicMock()), \
         patch("src.main.build_gpio_handler", MagicMock()), \
         patch("src.main.Session", MagicMock()), \
         patch("src.main.time.sleep", side_effect=KeyboardInterrupt), \
         patch("src.main._gpio_cleanup", gpio_cleanup_mock):
        try:
            main_mod.run()
        except KeyboardInterrupt:
            pass

    assert "audio.stop" in call_order, "audio.stop was never called"
    assert "gpio_cleanup" in call_order, "_gpio_cleanup was never called"
    assert call_order.index("audio.stop") < call_order.index("gpio_cleanup"), (
        "audio.stop must be called before gpio_cleanup"
    )
