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


@pytest.fixture
def tmp_error_queue(tmp_path):
    """Temporary SQLite DB file for error queue tests."""
    return str(tmp_path / "error_queue.db")


@pytest.fixture
def tmp_phone_book(tmp_path):
    """Temporary SQLite DB file for phone book tests."""
    return str(tmp_path / "phone_book.db")


@pytest.fixture
def tmp_plex_store(tmp_path):
    """Temporary SQLite DB file for plex_store tests."""
    return str(tmp_path / "plex_cache.db")


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
def mock_plex():
    """MockPlexClient instance for menu/session tests."""
    from src.plex_client import MockPlexClient
    return MockPlexClient()


@pytest.fixture
def mock_plex_store():
    """MockPlexStore instance for menu/session tests."""
    from src.plex_store import MockPlexStore
    return MockPlexStore()


@pytest.fixture
def mock_error_queue():
    """MockErrorQueue instance for menu/session tests."""
    from src.error_queue import MockErrorQueue
    return MockErrorQueue()
