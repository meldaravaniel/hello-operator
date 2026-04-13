# Shared pytest fixtures

import sys
from unittest.mock import MagicMock
import pytest
import tempfile
import os

# ---------------------------------------------------------------------------
# Mock sounddevice before any src.audio import so tests work without PortAudio
# ---------------------------------------------------------------------------
_sd_mock = MagicMock()
_sd_mock.play = MagicMock()
_sd_mock.stop = MagicMock()
_sd_mock.wait = MagicMock()
_sd_mock.OutputStream = MagicMock()
sys.modules.setdefault('sounddevice', _sd_mock)

# ---------------------------------------------------------------------------
# Mock mpd (python-mpd2) so tests work without a running MPD daemon
# ---------------------------------------------------------------------------
_mpd_mock = MagicMock()
sys.modules.setdefault('mpd', _mpd_mock)


@pytest.fixture
def tmp_error_queue(tmp_path):
    """Temporary SQLite DB file for error queue tests."""
    return str(tmp_path / "error_queue.db")


@pytest.fixture
def tmp_phone_book(tmp_path):
    """Temporary SQLite DB file for phone book tests."""
    return str(tmp_path / "phone_book.db")


@pytest.fixture
def tmp_media_store(tmp_path):
    """Temporary SQLite DB file for media_store tests."""
    return str(tmp_path / "media_cache.db")


# Backward-compat alias
@pytest.fixture
def tmp_plex_store(tmp_path):
    return str(tmp_path / "media_cache.db")


@pytest.fixture
def mock_audio():
    """MockAudio instance for menu/session tests."""
    from src.audio import MockAudio
    return MockAudio()


@pytest.fixture
def mock_tts():
    """MockTTS instance for menu/session tests."""
    from src.tts import MockTTS
    return MockTTS()


@pytest.fixture
def mock_media_client():
    """MockMediaClient instance for menu/session tests."""
    from src.plex_client import MockMediaClient
    return MockMediaClient()


# Backward-compat alias used by test_menu.py and test_session.py
@pytest.fixture
def mock_plex():
    from src.plex_client import MockMediaClient
    return MockMediaClient()


@pytest.fixture
def mock_media_store():
    """MockMediaStore instance for menu/session tests."""
    from src.media_store import MockMediaStore
    return MockMediaStore()


# Backward-compat alias
@pytest.fixture
def mock_plex_store():
    from src.media_store import MockMediaStore
    return MockMediaStore()


@pytest.fixture
def mock_error_queue():
    """MockErrorQueue instance for menu/session tests."""
    from src.error_queue import MockErrorQueue
    return MockErrorQueue()


@pytest.fixture
def mock_radio():
    """MockRadio instance for menu/session tests."""
    from src.radio import MockRadio
    return MockRadio()
