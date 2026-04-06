# Shared pytest fixtures

import pytest
import tempfile
import os


@pytest.fixture
def tmp_error_queue(tmp_path):
    """Temporary SQLite DB file for error queue tests."""
    return str(tmp_path / "error_queue.db")
