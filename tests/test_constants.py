"""Tests for F-12: Load secrets from environment variables.

Verifies that PLEX_TOKEN and PLEX_PLAYER_IDENTIFIER are loaded from the
environment, that missing required variables raise a clear error at import
time, and that PLEX_URL has a sensible default.
"""

import importlib
import sys
import os
import pytest


def _reimport_constants(env_overrides):
    """Remove src.constants from sys.modules and reimport it with a patched env.

    env_overrides: dict of env variable names to string values.
    Variables not in env_overrides are stripped from os.environ for the import.
    """
    # Build a clean environment with only the vars we want
    clean_env = {k: v for k, v in os.environ.items()
                 if k not in ("PLEX_TOKEN", "PLEX_PLAYER_IDENTIFIER", "PLEX_URL")}
    clean_env.update(env_overrides)

    # Remove the cached module so the top-level code re-executes
    sys.modules.pop("src.constants", None)

    import unittest.mock as mock
    with mock.patch.dict(os.environ, clean_env, clear=False):
        # Also explicitly remove the three plex vars if not in overrides
        for var in ("PLEX_TOKEN", "PLEX_PLAYER_IDENTIFIER", "PLEX_URL"):
            if var not in env_overrides:
                os.environ.pop(var, None)
        module = importlib.import_module("src.constants")

    # Restore sys.modules to avoid polluting other tests
    sys.modules.pop("src.constants", None)
    return module


class TestPlexTokenRequired:
    """PLEX_TOKEN is a required env variable."""

    def test_missing_plex_token_raises_on_import(self):
        """Importing src.constants without PLEX_TOKEN set must raise KeyError or RuntimeError."""
        with pytest.raises((KeyError, RuntimeError)):
            _reimport_constants({"PLEX_PLAYER_IDENTIFIER": "some-player-id"})

    def test_present_plex_token_is_used(self):
        """When PLEX_TOKEN is set, constants.PLEX_TOKEN equals its value."""
        module = _reimport_constants({
            "PLEX_TOKEN": "my_secret_token",
            "PLEX_PLAYER_IDENTIFIER": "some-player-id",
        })
        assert module.PLEX_TOKEN == "my_secret_token"

    def test_plex_token_not_hardcoded_placeholder(self):
        """constants.py must not contain a literal token string like 'YOUR_PLEX_TOKEN'."""
        module = _reimport_constants({
            "PLEX_TOKEN": "test_tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
        })
        assert module.PLEX_TOKEN != "YOUR_PLEX_TOKEN"


class TestPlexPlayerIdentifierRequired:
    """PLEX_PLAYER_IDENTIFIER is a required env variable."""

    def test_missing_player_identifier_raises_on_import(self):
        """Importing src.constants without PLEX_PLAYER_IDENTIFIER set must raise KeyError or RuntimeError."""
        with pytest.raises((KeyError, RuntimeError)):
            _reimport_constants({"PLEX_TOKEN": "tok"})

    def test_present_player_identifier_is_used(self):
        """When PLEX_PLAYER_IDENTIFIER is set, constants.PLEX_PLAYER_IDENTIFIER equals its value."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "my-player-id",
        })
        assert module.PLEX_PLAYER_IDENTIFIER == "my-player-id"

    def test_player_identifier_not_hardcoded_placeholder(self):
        """constants.py must not contain 'YOUR_PLEX_PLAYER_ID' as the returned value."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "real-player-id",
        })
        assert module.PLEX_PLAYER_IDENTIFIER != "YOUR_PLEX_PLAYER_ID"


class TestPlexUrlOptional:
    """PLEX_URL is optional with a sensible default."""

    def test_plex_url_defaults_to_localhost(self):
        """When PLEX_URL is not set, constants.PLEX_URL defaults to http://localhost:32400."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
        })
        assert module.PLEX_URL == "http://localhost:32400"

    def test_plex_url_env_override(self):
        """When PLEX_URL is set, constants.PLEX_URL equals its value."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
            "PLEX_URL": "http://192.168.1.100:32400",
        })
        assert module.PLEX_URL == "http://192.168.1.100:32400"


class TestDotEnvExample:
    """A .env.example file must exist and document required variables."""

    def test_env_example_exists(self):
        """A .env.example file must be present at the repository root."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_example_path = os.path.join(root, ".env.example")
        assert os.path.exists(env_example_path), ".env.example not found at repo root"

    def test_env_example_documents_plex_token(self):
        """PLEX_TOKEN must appear in .env.example."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_example_path = os.path.join(root, ".env.example")
        with open(env_example_path) as f:
            content = f.read()
        assert "PLEX_TOKEN" in content

    def test_env_example_documents_plex_player_identifier(self):
        """PLEX_PLAYER_IDENTIFIER must appear in .env.example."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_example_path = os.path.join(root, ".env.example")
        with open(env_example_path) as f:
            content = f.read()
        assert "PLEX_PLAYER_IDENTIFIER" in content

    def test_env_example_documents_plex_url(self):
        """PLEX_URL must appear in .env.example."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_example_path = os.path.join(root, ".env.example")
        with open(env_example_path) as f:
            content = f.read()
        assert "PLEX_URL" in content


class TestDigitWords:
    """F-17 — DIGIT_WORDS lives in constants, not duplicated in tts or menu."""

    def test_digit_words_in_constants(self):
        """constants.DIGIT_WORDS must be a complete 0–9 mapping."""
        import src.constants as c
        assert hasattr(c, "DIGIT_WORDS"), "DIGIT_WORDS not found in src.constants"
        dw = c.DIGIT_WORDS
        assert dw == {
            '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
            '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
        }

    def test_digit_words_not_defined_in_tts(self):
        """src/tts.py must not contain a local _DIGIT_WORDS definition."""
        src_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tts_path = os.path.join(src_root, "src", "tts.py")
        with open(tts_path) as f:
            content = f.read()
        assert "_DIGIT_WORDS" not in content, (
            "tts.py still defines _DIGIT_WORDS locally; it should import DIGIT_WORDS from constants"
        )

    def test_digit_words_not_defined_in_menu(self):
        """src/menu.py must not contain a local _DIGIT_WORDS definition."""
        src_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        menu_path = os.path.join(src_root, "src", "menu.py")
        with open(menu_path) as f:
            content = f.read()
        assert "_DIGIT_WORDS" not in content, (
            "menu.py still defines _DIGIT_WORDS locally; it should import DIGIT_WORDS from constants"
        )
