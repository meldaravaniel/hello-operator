"""Tests for src/constants.py — environment variable loading."""

import importlib
import sys
import os
import pytest


_CONTROLLED_VARS = (
    "MEDIA_BACKEND",
    "ASSISTANT_NUMBER",
    "MPD_HOST",
    "MPD_PORT",
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
    sys.modules.pop("src.constants", None)

    import unittest.mock as mock
    with mock.patch.dict(os.environ, env_overrides, clear=False):
        for var in _CONTROLLED_VARS:
            if var not in env_overrides:
                os.environ.pop(var, None)
        module = importlib.import_module("src.constants")

    sys.modules.pop("src.constants", None)
    return module


class TestAssistantNumberRequired:
    """ASSISTANT_NUMBER is a required env variable."""

    def test_present_assistant_number_is_used(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5559876"})
        assert module.ASSISTANT_NUMBER == "5559876"

    def test_assistant_number_is_string(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5550000"})
        assert isinstance(module.ASSISTANT_NUMBER, str)


class TestMediaBackend:
    """MEDIA_BACKEND defaults to mpd."""

    def test_media_backend_default(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5550000"})
        assert module.MEDIA_BACKEND == "mpd"

    def test_media_backend_override(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5550000", "MEDIA_BACKEND": "mopidy"})
        assert module.MEDIA_BACKEND == "mopidy"


class TestHookSwitchPin:
    """HOOK_SWITCH_PIN is optional with a default of 17."""

    def test_hook_pin_default(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5550000"})
        assert module.HOOK_SWITCH_PIN == 17

    def test_hook_pin_override(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5550000", "HOOK_SWITCH_PIN": "22"})
        assert module.HOOK_SWITCH_PIN == 22

    def test_hook_pin_is_int(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5550000"})
        assert isinstance(module.HOOK_SWITCH_PIN, int)

    def test_hook_pin_non_integer_raises(self):
        with pytest.raises((ValueError, RuntimeError)):
            _reimport_constants({"ASSISTANT_NUMBER": "5550000", "HOOK_SWITCH_PIN": "not-a-number"})


class TestPulseSwitchPin:
    """PULSE_SWITCH_PIN is optional with a default of 27."""

    def test_pulse_pin_default(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5550000"})
        assert module.PULSE_SWITCH_PIN == 27

    def test_pulse_pin_override(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5550000", "PULSE_SWITCH_PIN": "18"})
        assert module.PULSE_SWITCH_PIN == 18

    def test_pulse_pin_non_integer_raises(self):
        with pytest.raises((ValueError, RuntimeError)):
            _reimport_constants({"ASSISTANT_NUMBER": "5550000", "PULSE_SWITCH_PIN": "bad"})


class TestPiperOptionals:
    """PIPER_BINARY, PIPER_MODEL, TTS_CACHE_DIR are optional with defaults."""

    def test_piper_binary_default(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5550000"})
        assert module.PIPER_BINARY == "/usr/local/bin/piper"

    def test_piper_binary_override(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5550000", "PIPER_BINARY": "/opt/piper/piper"})
        assert module.PIPER_BINARY == "/opt/piper/piper"

    def test_piper_model_default(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5550000"})
        assert module.PIPER_MODEL == "/usr/local/share/piper/en_US-lessac-medium.onnx"

    def test_tts_cache_dir_default(self):
        module = _reimport_constants({"ASSISTANT_NUMBER": "5550000"})
        assert module.TTS_CACHE_DIR == "/var/cache/hello-operator/tts"


class TestConfigEnvExample:
    """config.env.example documents all env vars."""

    def _get_config_env_content(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_env_path = os.path.join(root, "config.env.example")
        with open(config_env_path) as f:
            return f.read()

    def test_config_env_example_exists(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(root, "config.env.example"))

    def test_config_env_example_documents_assistant_number(self):
        assert "ASSISTANT_NUMBER" in self._get_config_env_content()

    def test_config_env_example_documents_hook_switch_pin(self):
        assert "HOOK_SWITCH_PIN" in self._get_config_env_content()

    def test_config_env_example_documents_pulse_switch_pin(self):
        assert "PULSE_SWITCH_PIN" in self._get_config_env_content()

    def test_config_env_example_documents_piper_binary(self):
        assert "PIPER_BINARY" in self._get_config_env_content()

    def test_config_env_example_documents_piper_model(self):
        assert "PIPER_MODEL" in self._get_config_env_content()

    def test_config_env_example_documents_tts_cache_dir(self):
        assert "TTS_CACHE_DIR" in self._get_config_env_content()

    def test_config_env_example_does_not_mention_plex(self):
        assert "PLEX" not in self._get_config_env_content()


class TestDigitWords:
    """DIGIT_WORDS lives in constants, not duplicated in tts or menu."""

    def test_digit_words_in_constants(self):
        import src.constants as c
        assert hasattr(c, "DIGIT_WORDS")
        assert c.DIGIT_WORDS == {
            '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
            '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
        }

    def test_digit_words_not_defined_in_tts(self):
        src_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(src_root, "src", "tts.py")) as f:
            assert "_DIGIT_WORDS" not in f.read()

    def test_digit_words_not_defined_in_menu(self):
        src_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(src_root, "src", "menu.py")) as f:
            assert "_DIGIT_WORDS" not in f.read()


class TestAssistantNumberFormat:
    """Bug: ASSISTANT_NUMBER is required but its format is never validated.

    A value that is not exactly PHONE_NUMBER_LENGTH digits will be accepted at
    import time but the assistant will be silently unreachable: the direct-dial
    comparisons in menu.py check len(digits) == PHONE_NUMBER_LENGTH, so a
    shorter or longer number never matches.
    """

    def test_assistant_number_too_short_raises(self):
        """ASSISTANT_NUMBER with fewer than 7 digits must raise RuntimeError at import."""
        with pytest.raises(RuntimeError, match="ASSISTANT_NUMBER"):
            _reimport_constants({"ASSISTANT_NUMBER": "12345"})  # 5 digits

    def test_assistant_number_too_long_raises(self):
        """ASSISTANT_NUMBER with more than 7 digits must raise RuntimeError at import."""
        with pytest.raises(RuntimeError, match="ASSISTANT_NUMBER"):
            _reimport_constants({"ASSISTANT_NUMBER": "12345678"})  # 8 digits

    def test_assistant_number_non_numeric_raises(self):
        """ASSISTANT_NUMBER containing non-digit characters must raise RuntimeError."""
        with pytest.raises(RuntimeError, match="ASSISTANT_NUMBER"):
            _reimport_constants({"ASSISTANT_NUMBER": "555ABCD"})
