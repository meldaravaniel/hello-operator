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
