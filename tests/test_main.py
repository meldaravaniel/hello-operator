"""Tests for src/main.py."""

import json
import logging
from unittest.mock import MagicMock, patch, call

import pytest

from src.interfaces import RadioStation
import src.main as main_module
from src.main import load_radio_stations, build_media_client, _PRERENDER_SCRIPTS


# ---------------------------------------------------------------------------
# load_radio_stations
# ---------------------------------------------------------------------------


class TestLoadRadioStations:
    def test_returns_radiostation_objects(self, tmp_path):
        p = tmp_path / "stations.json"
        p.write_text(json.dumps([
            {"name": "KEXP", "frequency_mhz": 90.3, "phone_number": "5550903"}
        ]))
        stations = load_radio_stations(str(p))
        assert len(stations) == 1
        assert isinstance(stations[0], RadioStation)

    def test_populates_name_and_phone_number(self, tmp_path):
        p = tmp_path / "stations.json"
        p.write_text(json.dumps([
            {"name": "KEXP", "frequency_mhz": 90.3, "phone_number": "5550903"}
        ]))
        s = load_radio_stations(str(p))[0]
        assert s.name == "KEXP"
        assert s.phone_number == "5550903"

    def test_converts_frequency_mhz_to_hz(self, tmp_path):
        p = tmp_path / "stations.json"
        p.write_text(json.dumps([
            {"name": "Test", "frequency_mhz": 90.3, "phone_number": "5550903"}
        ]))
        s = load_radio_stations(str(p))[0]
        assert s.frequency_hz == pytest.approx(90_300_000.0)

    def test_returns_multiple_stations(self, tmp_path):
        p = tmp_path / "stations.json"
        p.write_text(json.dumps([
            {"name": "KEXP",  "frequency_mhz": 90.3, "phone_number": "5550903"},
            {"name": "KNKX",  "frequency_mhz": 88.5, "phone_number": "5550885"},
        ]))
        stations = load_radio_stations(str(p))
        assert len(stations) == 2
        assert stations[1].name == "KNKX"

    def test_returns_empty_list_for_empty_array(self, tmp_path):
        p = tmp_path / "stations.json"
        p.write_text("[]")
        assert load_radio_stations(str(p)) == []

    def test_returns_empty_list_when_file_not_found(self, tmp_path):
        assert load_radio_stations(str(tmp_path / "missing.json")) == []

    def test_logs_warning_when_file_not_found(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            load_radio_stations(str(tmp_path / "missing.json"))
        assert any("not found" in r.message.lower() for r in caplog.records)

    def test_returns_empty_list_on_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not valid json {")
        assert load_radio_stations(str(p)) == []

    def test_logs_warning_on_invalid_json(self, tmp_path, caplog):
        p = tmp_path / "bad.json"
        p.write_text("not valid json {")
        with caplog.at_level(logging.WARNING):
            load_radio_stations(str(p))
        assert any("parse" in r.message.lower() for r in caplog.records)

    def test_returns_empty_list_on_missing_key(self, tmp_path):
        p = tmp_path / "stations.json"
        # frequency_mhz is absent
        p.write_text(json.dumps([{"name": "KEXP", "phone_number": "5550903"}]))
        assert load_radio_stations(str(p)) == []

    def test_logs_warning_on_missing_key(self, tmp_path, caplog):
        p = tmp_path / "stations.json"
        p.write_text(json.dumps([{"name": "KEXP", "phone_number": "5550903"}]))
        with caplog.at_level(logging.WARNING):
            load_radio_stations(str(p))
        assert any("parse" in r.message.lower() for r in caplog.records)

    def test_returns_empty_list_when_frequency_is_null(self, tmp_path):
        p = tmp_path / "stations.json"
        p.write_text(json.dumps([
            {"name": "X", "frequency_mhz": None, "phone_number": "5550903"}
        ]))
        assert load_radio_stations(str(p)) == []

    def test_returns_empty_list_on_empty_file(self, tmp_path):
        p = tmp_path / "stations.json"
        p.write_text("")
        assert load_radio_stations(str(p)) == []


# ---------------------------------------------------------------------------
# build_media_client
# ---------------------------------------------------------------------------


class TestBuildMediaClient:
    def test_returns_mpd_client_for_mpd_backend(self, monkeypatch):
        monkeypatch.setattr(main_module, "MEDIA_BACKEND", "mpd")
        with patch("src.main.MPDClient") as MockMPD:
            client = build_media_client()
        assert client is MockMPD.return_value

    def test_returns_mpd_client_for_mopidy_backend(self, monkeypatch):
        monkeypatch.setattr(main_module, "MEDIA_BACKEND", "mopidy")
        with patch("src.main.MPDClient") as MockMPD:
            client = build_media_client()
        assert client is MockMPD.return_value

    def test_passes_host_and_port(self, monkeypatch):
        monkeypatch.setattr(main_module, "MEDIA_BACKEND", "mpd")
        monkeypatch.setattr(main_module, "MPD_HOST", "192.168.1.5")
        monkeypatch.setattr(main_module, "MPD_PORT", 6601)
        with patch("src.main.MPDClient") as MockMPD:
            build_media_client()
        MockMPD.assert_called_once_with(host="192.168.1.5", port=6601)


# ---------------------------------------------------------------------------
# _PRERENDER_SCRIPTS coverage
# ---------------------------------------------------------------------------


class TestPrerenderScripts:
    _expected_keys = {
        "operator_opener", "greeting", "extension_hint",
        "playing_menu_default", "playing_menu_on_hold",
        "playing_menu_last_track", "playing_menu_on_hold_last_track",
        "not_in_service",
        "browse_prompt_playlist", "browse_prompt_artist",
        "browse_prompt_genre", "browse_prompt_album",
        "browse_prompt_next_letter",
        "media_failure", "retry_prompt", "no_content",
        "assistant_all_clear", "assistant_status_intro",
        "assistant_end_of_messages", "assistant_navigation",
        "assistant_valediction_messages",
        "assistant_refresh_success", "assistant_refresh_failure",
        "shuffle_connecting", "radio_playing_menu",
    }

    def test_contains_all_expected_keys(self):
        assert self._expected_keys == set(_PRERENDER_SCRIPTS.keys())

    def test_all_values_are_non_empty_strings(self):
        for key, value in _PRERENDER_SCRIPTS.items():
            assert isinstance(value, str) and value, f"Script '{key}' is empty or not a string"


# ---------------------------------------------------------------------------
# run() — wiring and shutdown behaviour
# ---------------------------------------------------------------------------


class TestRun:
    @pytest.fixture
    def patch_run_deps(self):
        """Replace every hardware / I/O dependency inside run() with mocks.
        time.sleep raises KeyboardInterrupt so the event loop exits immediately."""
        with (
            patch("src.main.os.makedirs") as makedirs,
            patch("src.main.SqliteErrorQueue") as ErrorQueue,
            patch("src.main.PhoneBook") as PhoneBook,
            patch("src.main.load_radio_stations", return_value=[]) as load_stations,
            patch("src.main.DigitalInputDevice") as DigInput,
            patch("src.main.Button") as ButtonCls,
            patch("src.main.OutputDevice") as OutDev,
            patch("src.main.SounddeviceAudio") as Audio,
            patch("src.main.PiperTTS") as TTS,
            patch("src.main.build_media_client") as build_client,
            patch("src.main.MediaStore") as Store,
            patch("src.main.RtlFmRadio") as Radio,
            patch("src.main.Menu") as MenuCls,
            patch("src.main.Phone") as PhoneCls,
            patch("src.main.time.sleep", side_effect=KeyboardInterrupt),
        ):
            yield {
                "makedirs": makedirs,
                "ErrorQueue": ErrorQueue,
                "PhoneBook": PhoneBook,
                "load_stations": load_stations,
                "DigInput": DigInput,
                "ButtonCls": ButtonCls,
                "OutDev": OutDev,
                "Audio": Audio,
                "TTS": TTS,
                "build_client": build_client,
                "Store": Store,
                "Radio": Radio,
                "MenuCls": MenuCls,
                "PhoneCls": PhoneCls,
            }

    def test_creates_db_directory(self, patch_run_deps):
        main_module.run()
        patch_run_deps["makedirs"].assert_called_once_with(
            main_module._DB_DIR, exist_ok=True
        )

    def test_prerender_called_with_all_scripts(self, patch_run_deps):
        main_module.run()
        tts = patch_run_deps["TTS"].return_value
        tts.prerender.assert_called_once_with(_PRERENDER_SCRIPTS)

    def test_phone_is_started(self, patch_run_deps):
        main_module.run()
        patch_run_deps["PhoneCls"].return_value.start.assert_called_once()

    def test_phone_is_stopped_on_keyboard_interrupt(self, patch_run_deps):
        main_module.run()
        patch_run_deps["PhoneCls"].return_value.stop.assert_called_once()

    def test_audio_is_stopped_on_keyboard_interrupt(self, patch_run_deps):
        main_module.run()
        patch_run_deps["Audio"].return_value.stop.assert_called_once()

    def test_seeds_each_radio_station_into_phone_book(self, patch_run_deps):
        stations = [
            RadioStation(name="KEXP",  frequency_hz=90_300_000.0, phone_number="5550903"),
            RadioStation(name="KNKX",  frequency_hz=88_500_000.0, phone_number="5550885"),
        ]
        patch_run_deps["load_stations"].return_value = stations
        main_module.run()
        phone_book = patch_run_deps["PhoneBook"].return_value
        assert phone_book.seed.call_count == 2
        phone_book.seed.assert_any_call(
            phone_number="5550903",
            media_key="radio:90300000.0",
            media_type="radio",
            name="KEXP",
        )
        phone_book.seed.assert_any_call(
            phone_number="5550885",
            media_key="radio:88500000.0",
            media_type="radio",
            name="KNKX",
        )

    def test_no_seed_calls_when_no_stations(self, patch_run_deps):
        patch_run_deps["load_stations"].return_value = []
        main_module.run()
        patch_run_deps["PhoneBook"].return_value.seed.assert_not_called()

    def test_phone_constructed_with_menu_and_audio(self, patch_run_deps):
        main_module.run()
        PhoneCls = patch_run_deps["PhoneCls"]
        Audio = patch_run_deps["Audio"]
        MenuCls = patch_run_deps["MenuCls"]
        args, kwargs = PhoneCls.call_args
        # Menu and Audio instances must be passed through to Phone
        assert MenuCls.return_value in (list(args) + list(kwargs.values()))
        assert Audio.return_value in (list(args) + list(kwargs.values()))

    def test_menu_constructed_with_media_store_and_phone_book(self, patch_run_deps):
        main_module.run()
        MenuCls = patch_run_deps["MenuCls"]
        Store = patch_run_deps["Store"]
        PhoneBook = patch_run_deps["PhoneBook"]
        _, kwargs = MenuCls.call_args
        assert kwargs.get("media_store") is Store.return_value
        assert kwargs.get("phone_book") is PhoneBook.return_value

    def test_stop_called_on_unexpected_loop_exception(self, patch_run_deps):
        """finally block runs even when the event loop raises an unexpected exception."""
        with patch("src.main.time.sleep", side_effect=RuntimeError("boom")):
            main_module.run()  # except Exception swallows it; finally still fires
        patch_run_deps["Audio"].return_value.stop.assert_called_once()
        patch_run_deps["PhoneCls"].return_value.stop.assert_called_once()
