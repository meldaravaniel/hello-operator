"""Tests for RadioInterface, RtlFmRadio, and MockRadio."""

import subprocess
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# MockRadio tests
# ---------------------------------------------------------------------------

def test_mock_radio_initial_state(mock_radio):
    """is_playing() is False before any call."""
    assert mock_radio.is_playing() is False


def test_mock_radio_play(mock_radio):
    """After play(90_300_000.0), is_playing() is True and calls contains the entry."""
    mock_radio.play(90_300_000.0)
    assert mock_radio.is_playing() is True
    assert ('play', 90_300_000.0) in mock_radio.calls


def test_mock_radio_stop(mock_radio):
    """After play() then stop(), is_playing() is False and ('stop',) is in calls."""
    mock_radio.play(90_300_000.0)
    mock_radio.stop()
    assert mock_radio.is_playing() is False
    assert ('stop',) in mock_radio.calls


def test_mock_radio_set_playing(mock_radio):
    """set_playing(True) makes is_playing() True; set_playing(False) returns it to False."""
    mock_radio.set_playing(True)
    assert mock_radio.is_playing() is True
    mock_radio.set_playing(False)
    assert mock_radio.is_playing() is False


def test_rtl_fm_raises_when_not_on_path(monkeypatch):
    """RtlFmRadio().play() raises RuntimeError with 'rtl_fm' in the message when rtl_fm is not on PATH."""
    import src.radio as radio_module
    monkeypatch.setattr(radio_module.shutil, 'which', lambda _: None)
    radio = radio_module.RtlFmRadio()
    with pytest.raises(RuntimeError, match="rtl_fm"):
        radio.play(90_300_000.0)
