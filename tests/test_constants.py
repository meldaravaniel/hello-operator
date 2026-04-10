"""Tests for F-12: Load secrets from environment variables.

Verifies that PLEX_TOKEN and PLEX_PLAYER_IDENTIFIER are loaded from the
environment, that missing required variables raise a clear error at import
time, and that PLEX_URL has a sensible default.
"""

import importlib
import sys
import os
import pytest


_CONTROLLED_VARS = (
    "PLEX_TOKEN",
    "PLEX_PLAYER_IDENTIFIER",
    "PLEX_URL",
    "ASSISTANT_NUMBER",
    "HOOK_SWITCH_PIN",
    "PULSE_SWITCH_PIN",
    "PIPER_BINARY",
    "PIPER_MODEL",
    "TTS_CACHE_DIR",
)


def _reimport_constants(env_overrides):
    """Remove src.constants from sys.modules and reimport it with a patched env.

    env_overrides: dict of env variable names to string values.
    Variables not in env_overrides are stripped from os.environ for the import.
    """
    # Remove the cached module so the top-level code re-executes
    sys.modules.pop("src.constants", None)

    import unittest.mock as mock
    with mock.patch.dict(os.environ, env_overrides, clear=False):
        # Explicitly remove all controlled vars that are not in overrides
        for var in _CONTROLLED_VARS:
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


class TestAssistantNumberRequired:
    """ASSISTANT_NUMBER is a required env variable (f27)."""

    def test_missing_assistant_number_raises(self):
        """Importing src.constants without ASSISTANT_NUMBER set must raise RuntimeError."""
        with pytest.raises(RuntimeError, match="ASSISTANT_NUMBER"):
            _reimport_constants({
                "PLEX_TOKEN": "tok",
                "PLEX_PLAYER_IDENTIFIER": "pid",
            })

    def test_present_assistant_number_is_used(self):
        """When ASSISTANT_NUMBER is set, constants.ASSISTANT_NUMBER equals its value."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
            "ASSISTANT_NUMBER": "5559876",
        })
        assert module.ASSISTANT_NUMBER == "5559876"

    def test_assistant_number_is_string(self):
        """constants.ASSISTANT_NUMBER must be a str, not an int."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
            "ASSISTANT_NUMBER": "5550000",
        })
        assert isinstance(module.ASSISTANT_NUMBER, str)


class TestHookSwitchPin:
    """HOOK_SWITCH_PIN is optional with a default of 17 (f27)."""

    def test_hook_pin_default(self):
        """When HOOK_SWITCH_PIN is not set, constants.HOOK_SWITCH_PIN defaults to 17."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
            "ASSISTANT_NUMBER": "5550000",
        })
        assert module.HOOK_SWITCH_PIN == 17

    def test_hook_pin_override(self):
        """When HOOK_SWITCH_PIN=22, constants.HOOK_SWITCH_PIN is 22 (as int)."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
            "ASSISTANT_NUMBER": "5550000",
            "HOOK_SWITCH_PIN": "22",
        })
        assert module.HOOK_SWITCH_PIN == 22

    def test_hook_pin_is_int(self):
        """constants.HOOK_SWITCH_PIN must be an int."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
            "ASSISTANT_NUMBER": "5550000",
        })
        assert isinstance(module.HOOK_SWITCH_PIN, int)

    def test_hook_pin_non_integer_raises(self):
        """Setting HOOK_SWITCH_PIN to a non-integer string raises ValueError at import time."""
        with pytest.raises((ValueError, RuntimeError)):
            _reimport_constants({
                "PLEX_TOKEN": "tok",
                "PLEX_PLAYER_IDENTIFIER": "pid",
                "ASSISTANT_NUMBER": "5550000",
                "HOOK_SWITCH_PIN": "not-a-number",
            })


class TestPulseSwitchPin:
    """PULSE_SWITCH_PIN is optional with a default of 27 (f27)."""

    def test_pulse_pin_default(self):
        """When PULSE_SWITCH_PIN is not set, constants.PULSE_SWITCH_PIN defaults to 27."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
            "ASSISTANT_NUMBER": "5550000",
        })
        assert module.PULSE_SWITCH_PIN == 27

    def test_pulse_pin_override(self):
        """When PULSE_SWITCH_PIN=18, constants.PULSE_SWITCH_PIN is 18 (as int)."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
            "ASSISTANT_NUMBER": "5550000",
            "PULSE_SWITCH_PIN": "18",
        })
        assert module.PULSE_SWITCH_PIN == 18

    def test_pulse_pin_non_integer_raises(self):
        """Setting PULSE_SWITCH_PIN to a non-integer string raises ValueError at import time."""
        with pytest.raises((ValueError, RuntimeError)):
            _reimport_constants({
                "PLEX_TOKEN": "tok",
                "PLEX_PLAYER_IDENTIFIER": "pid",
                "ASSISTANT_NUMBER": "5550000",
                "PULSE_SWITCH_PIN": "bad",
            })


class TestPiperOptionals:
    """PIPER_BINARY, PIPER_MODEL, TTS_CACHE_DIR are optional with defaults (f27)."""

    def test_piper_binary_default(self):
        """When PIPER_BINARY is not set, constants.PIPER_BINARY defaults to /usr/local/bin/piper."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
            "ASSISTANT_NUMBER": "5550000",
        })
        assert module.PIPER_BINARY == "/usr/local/bin/piper"

    def test_piper_binary_override(self):
        """When PIPER_BINARY is set, constants.PIPER_BINARY equals its value."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
            "ASSISTANT_NUMBER": "5550000",
            "PIPER_BINARY": "/opt/piper/piper",
        })
        assert module.PIPER_BINARY == "/opt/piper/piper"

    def test_piper_model_default(self):
        """When PIPER_MODEL is not set, constants.PIPER_MODEL defaults to the lessac model path."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
            "ASSISTANT_NUMBER": "5550000",
        })
        assert module.PIPER_MODEL == "/usr/local/share/piper/en_US-lessac-medium.onnx"

    def test_tts_cache_dir_default(self):
        """When TTS_CACHE_DIR is not set, constants.TTS_CACHE_DIR defaults to /var/cache/hello-operator/tts."""
        module = _reimport_constants({
            "PLEX_TOKEN": "tok",
            "PLEX_PLAYER_IDENTIFIER": "pid",
            "ASSISTANT_NUMBER": "5550000",
        })
        assert module.TTS_CACHE_DIR == "/var/cache/hello-operator/tts"


class TestConfigEnvExample:
    """config.env.example at project root documents all env vars (f27)."""

    def _get_config_env_content(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_env_path = os.path.join(root, "config.env.example")
        with open(config_env_path) as f:
            return f.read()

    def test_config_env_example_exists(self):
        """config.env.example must be present at the repository root."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_env_path = os.path.join(root, "config.env.example")
        assert os.path.exists(config_env_path), "config.env.example not found at repo root"

    def test_config_env_example_documents_plex_token(self):
        """PLEX_TOKEN must appear in config.env.example."""
        assert "PLEX_TOKEN" in self._get_config_env_content()

    def test_config_env_example_documents_plex_player_identifier(self):
        """PLEX_PLAYER_IDENTIFIER must appear in config.env.example."""
        assert "PLEX_PLAYER_IDENTIFIER" in self._get_config_env_content()

    def test_config_env_example_documents_plex_url(self):
        """PLEX_URL must appear in config.env.example."""
        assert "PLEX_URL" in self._get_config_env_content()

    def test_config_env_example_documents_assistant_number(self):
        """ASSISTANT_NUMBER must appear in config.env.example."""
        assert "ASSISTANT_NUMBER" in self._get_config_env_content()

    def test_config_env_example_documents_hook_switch_pin(self):
        """HOOK_SWITCH_PIN must appear in config.env.example."""
        assert "HOOK_SWITCH_PIN" in self._get_config_env_content()

    def test_config_env_example_documents_pulse_switch_pin(self):
        """PULSE_SWITCH_PIN must appear in config.env.example."""
        assert "PULSE_SWITCH_PIN" in self._get_config_env_content()

    def test_config_env_example_documents_piper_binary(self):
        """PIPER_BINARY must appear in config.env.example."""
        assert "PIPER_BINARY" in self._get_config_env_content()

    def test_config_env_example_documents_piper_model(self):
        """PIPER_MODEL must appear in config.env.example."""
        assert "PIPER_MODEL" in self._get_config_env_content()

    def test_config_env_example_documents_tts_cache_dir(self):
        """TTS_CACHE_DIR must appear in config.env.example."""
        assert "TTS_CACHE_DIR" in self._get_config_env_content()


class TestNoTodoComments:
    """constants.py must not contain TODO comments for the moved variables (f27)."""

    def test_no_todo_for_assistant_number(self):
        """constants.py must not have a TODO comment on ASSISTANT_NUMBER line."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        constants_path = os.path.join(root, "src", "constants.py")
        with open(constants_path) as f:
            content = f.read()
        for line in content.splitlines():
            if "ASSISTANT_NUMBER" in line and "TODO" in line:
                pytest.fail(f"TODO comment found on ASSISTANT_NUMBER line: {line!r}")

    def test_no_todo_for_piper_binary(self):
        """constants.py must not have a TODO comment on PIPER_BINARY line."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        constants_path = os.path.join(root, "src", "constants.py")
        with open(constants_path) as f:
            content = f.read()
        for line in content.splitlines():
            if "PIPER_BINARY" in line and "TODO" in line:
                pytest.fail(f"TODO comment found on PIPER_BINARY line: {line!r}")

    def test_no_todo_for_hook_switch_pin(self):
        """constants.py must not have a TODO comment on HOOK_SWITCH_PIN line."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        constants_path = os.path.join(root, "src", "constants.py")
        with open(constants_path) as f:
            content = f.read()
        for line in content.splitlines():
            if "HOOK_SWITCH_PIN" in line and "TODO" in line:
                pytest.fail(f"TODO comment found on HOOK_SWITCH_PIN line: {line!r}")


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
