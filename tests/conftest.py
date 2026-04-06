# Shared pytest fixtures

import pytest
import tempfile
import os


@pytest.fixture
def tmp_error_queue(tmp_path):
    """Temporary SQLite DB file for error queue tests."""
    return str(tmp_path / "error_queue.db")


@pytest.fixture
def tmp_phone_book(tmp_path):
    """Temporary SQLite DB file for phone book tests."""
    return str(tmp_path / "phone_book.db")
