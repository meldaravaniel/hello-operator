"""Tests for the web configuration interface (web/app.py).

All file I/O is redirected to pytest's tmp_path fixture.
Service management (get_service_status, restart_service) is stubbed with
monkeypatch so no systemd or sudo is required.
"""

import json
import subprocess
from unittest.mock import MagicMock, Mock

import pytest

import web.app as wa


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config_file(tmp_path):
    """A pre-populated config.env in tmp_path."""
    p = tmp_path / "config.env"
    p.write_text(
        "# Plex\n"
        'PLEX_TOKEN="existingtoken"\n'
        'PLEX_URL="http://localhost:32400"\n'
        'PLEX_PLAYER_IDENTIFIER="abc123"\n'
        "# Phone\n"
        'ASSISTANT_NUMBER="5550000"\n'
    )
    return p


@pytest.fixture
def radio_file(tmp_path):
    """A pre-populated radio_stations.json in tmp_path."""
    p = tmp_path / "radio_stations.json"
    p.write_text(
        json.dumps([{"name": "KEXP", "frequency_mhz": 90.3, "phone_number": "5550903"}])
    )
    return p


@pytest.fixture
def docs_dir(tmp_path):
    """Minimal documentation tree under tmp_path (matches DOC_PAGES entries)."""
    (tmp_path / "README.md").write_text("# Hello Operator\n\nReadme content.\n")
    (tmp_path / "INSTALL.md").write_text("# Installation\n\nInstall content.\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "AMP_SETUP.md").write_text("# Amp Setup\n\nAmp content.\n")
    return tmp_path


@pytest.fixture
def patch_paths(monkeypatch, tmp_path, config_file, radio_file):
    """Redirect all file-path constants in web.app to tmp_path locations."""
    monkeypatch.setattr(wa, "CONFIG_ENV_PATH", config_file)
    monkeypatch.setattr(wa, "RADIO_JSON_PATH", radio_file)
    monkeypatch.setattr(wa, "DOCS_ROOT", tmp_path)


@pytest.fixture
def mock_service_ok(monkeypatch):
    """Stub service functions to return 'active' / success."""
    monkeypatch.setattr(wa, "get_service_status", lambda: "active")
    monkeypatch.setattr(wa, "restart_service", lambda: (True, ""))


@pytest.fixture
def client(patch_paths, mock_service_ok):
    """Flask test client with paths and service functions fully mocked."""
    wa.app.config["TESTING"] = True
    return wa.app.test_client()


# ---------------------------------------------------------------------------
# read_config_env
# ---------------------------------------------------------------------------


class TestReadConfigEnv:
    def test_empty_file_returns_empty_dict(self, monkeypatch, tmp_path):
        p = tmp_path / "config.env"
        p.write_text("")
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        assert wa.read_config_env() == {}

    def test_parses_bare_key_value_pairs(self, monkeypatch, tmp_path):
        p = tmp_path / "config.env"
        p.write_text("FOO=bar\nBAZ=qux\n")
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        assert wa.read_config_env() == {"FOO": "bar", "BAZ": "qux"}

    def test_strips_surrounding_double_quotes(self, monkeypatch, tmp_path):
        p = tmp_path / "config.env"
        p.write_text('TOKEN="mytoken"\n')
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        assert wa.read_config_env()["TOKEN"] == "mytoken"

    def test_ignores_comment_lines(self, monkeypatch, tmp_path):
        p = tmp_path / "config.env"
        p.write_text("# this is a comment\nFOO=bar\n")
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        result = wa.read_config_env()
        assert list(result.keys()) == ["FOO"]

    def test_ignores_blank_lines(self, monkeypatch, tmp_path):
        p = tmp_path / "config.env"
        p.write_text("\nFOO=bar\n\n")
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        assert wa.read_config_env() == {"FOO": "bar"}

    def test_file_not_found_returns_empty_dict(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", tmp_path / "missing.env")
        assert wa.read_config_env() == {}


# ---------------------------------------------------------------------------
# write_config_env
# ---------------------------------------------------------------------------


class TestWriteConfigEnv:
    def test_updates_existing_key_in_place(self, monkeypatch, tmp_path):
        p = tmp_path / "config.env"
        p.write_text("FOO=old\nBAR=baz\n")
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        wa.write_config_env({"FOO": "new"})
        lines = p.read_text().splitlines()
        assert 'FOO="new"' in lines
        assert any("BAR" in line for line in lines)

    def test_preserves_comment_lines(self, monkeypatch, tmp_path):
        p = tmp_path / "config.env"
        p.write_text("# my comment\nFOO=old\n")
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        wa.write_config_env({"FOO": "new"})
        assert "# my comment" in p.read_text()

    def test_preserves_unrelated_keys(self, monkeypatch, tmp_path):
        p = tmp_path / "config.env"
        p.write_text("FOO=keep\nBAR=also\n")
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        wa.write_config_env({"BAR": "updated"})
        text = p.read_text()
        assert "FOO=keep" in text
        assert 'BAR="updated"' in text

    def test_appends_key_not_in_file(self, monkeypatch, tmp_path):
        p = tmp_path / "config.env"
        p.write_text("EXISTING=value\n")
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        wa.write_config_env({"NEWKEY": "newval"})
        text = p.read_text()
        assert "EXISTING=value" in text
        assert 'NEWKEY="newval"' in text

    def test_creates_file_if_missing(self, monkeypatch, tmp_path):
        p = tmp_path / "new.env"
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        wa.write_config_env({"FOO": "bar"})
        assert p.exists()
        assert 'FOO="bar"' in p.read_text()

    def test_quotes_values_with_spaces(self, monkeypatch, tmp_path):
        p = tmp_path / "config.env"
        p.write_text("")
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        wa.write_config_env({"MY_KEY": "a value with spaces"})
        assert 'MY_KEY="a value with spaces"' in p.read_text()

    def test_escapes_embedded_double_quotes(self, monkeypatch, tmp_path):
        p = tmp_path / "config.env"
        p.write_text("")
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        wa.write_config_env({"TOKEN": 'has"quote'})
        assert r'has\"quote' in p.read_text()

    def test_roundtrip_survives_read_write_read(self, monkeypatch, tmp_path):
        p = tmp_path / "config.env"
        p.write_text('PLEX_URL="http://localhost:32400"\n')
        monkeypatch.setattr(wa, "CONFIG_ENV_PATH", p)
        wa.write_config_env({"PLEX_URL": "http://192.168.1.10:32400"})
        assert wa.read_config_env()["PLEX_URL"] == "http://192.168.1.10:32400"


# ---------------------------------------------------------------------------
# read_radio_stations / write_radio_stations
# ---------------------------------------------------------------------------


class TestRadioIO:
    def test_read_returns_list_of_dicts(self, monkeypatch, tmp_path):
        p = tmp_path / "radio.json"
        p.write_text(json.dumps([{"name": "KEXP", "frequency_mhz": 90.3, "phone_number": "5550903"}]))
        monkeypatch.setattr(wa, "RADIO_JSON_PATH", p)
        stations = wa.read_radio_stations()
        assert len(stations) == 1
        assert stations[0]["name"] == "KEXP"

    def test_read_file_not_found_returns_empty_list(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wa, "RADIO_JSON_PATH", tmp_path / "missing.json")
        assert wa.read_radio_stations() == []

    def test_read_invalid_json_returns_empty_list(self, monkeypatch, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not valid json {")
        monkeypatch.setattr(wa, "RADIO_JSON_PATH", p)
        assert wa.read_radio_stations() == []

    def test_write_produces_valid_json_file(self, monkeypatch, tmp_path):
        p = tmp_path / "radio.json"
        monkeypatch.setattr(wa, "RADIO_JSON_PATH", p)
        stations = [{"name": "KNKX", "frequency_mhz": 88.5, "phone_number": "5550885"}]
        wa.write_radio_stations(stations)
        assert json.loads(p.read_text()) == stations

    def test_roundtrip(self, monkeypatch, tmp_path):
        p = tmp_path / "radio.json"
        monkeypatch.setattr(wa, "RADIO_JSON_PATH", p)
        original = [{"name": "Test FM", "frequency_mhz": 99.9, "phone_number": "5550999"}]
        wa.write_radio_stations(original)
        assert wa.read_radio_stations() == original


# ---------------------------------------------------------------------------
# get_service_status
# ---------------------------------------------------------------------------


class TestGetServiceStatus:
    def test_returns_active_when_service_running(self, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(stdout="active\n", returncode=0))
        monkeypatch.setattr(subprocess, "run", mock_run)
        assert wa.get_service_status() == "active"

    def test_returns_inactive_when_stopped(self, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(stdout="inactive\n", returncode=3))
        monkeypatch.setattr(subprocess, "run", mock_run)
        assert wa.get_service_status() == "inactive"

    def test_returns_unknown_on_subprocess_exception(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=OSError("not found")))
        assert wa.get_service_status() == "unknown"


# ---------------------------------------------------------------------------
# restart_service
# ---------------------------------------------------------------------------


class TestRestartService:
    def test_success_returns_true_and_empty_message(self, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
        monkeypatch.setattr(subprocess, "run", mock_run)
        ok, err = wa.restart_service()
        assert ok is True
        assert err == ""

    def test_non_zero_exit_returns_false_with_stderr(self, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(returncode=1, stderr="Unit not found"))
        monkeypatch.setattr(subprocess, "run", mock_run)
        ok, err = wa.restart_service()
        assert ok is False
        assert "Unit not found" in err

    def test_exception_returns_false_with_message(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=OSError("systemctl missing")))
        ok, err = wa.restart_service()
        assert ok is False
        assert "systemctl missing" in err


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


class TestRouteIndex:
    def test_returns_200(self, client):
        assert client.get("/").status_code == 200

    def test_shows_running_badge_when_active(self, client, monkeypatch):
        monkeypatch.setattr(wa, "get_service_status", lambda: "active")
        assert b"Running" in client.get("/").data

    def test_shows_stopped_badge_when_inactive(self, client, monkeypatch):
        monkeypatch.setattr(wa, "get_service_status", lambda: "inactive")
        assert b"Stopped" in client.get("/").data

    def test_shows_failed_badge_on_failure(self, client, monkeypatch):
        monkeypatch.setattr(wa, "get_service_status", lambda: "failed")
        assert b"Failed" in client.get("/").data


# ---------------------------------------------------------------------------
# GET /docs  and  GET /docs/<slug>
# ---------------------------------------------------------------------------


class TestRouteDocs:
    def test_docs_index_redirects_to_first_available_page(self, client, docs_dir):
        resp = client.get("/docs")
        assert resp.status_code == 302
        assert "/docs/" in resp.headers["Location"]

    def test_docs_index_with_no_files_returns_200(self, client):
        # No docs created under tmp_path — should render empty list, not crash
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_docs_page_returns_200(self, client, docs_dir):
        resp = client.get("/docs/README")
        assert resp.status_code == 200

    def test_docs_page_embeds_raw_markdown_for_rendering(self, client, docs_dir):
        resp = client.get("/docs/README")
        # Raw markdown is JSON-encoded into the page for client-side rendering
        assert b"Hello Operator" in resp.data

    def test_docs_page_unknown_slug_returns_404(self, client):
        assert client.get("/docs/completely_unknown").status_code == 404

    def test_docs_page_known_slug_but_missing_file_returns_404(self, client):
        # README is in DOC_PAGES but the file was not created in tmp_path
        assert client.get("/docs/README").status_code == 404

    def test_docs_page_renders_sidebar_links(self, client, docs_dir):
        resp = client.get("/docs/README")
        assert b"/docs/" in resp.data


# ---------------------------------------------------------------------------
# GET /config
# ---------------------------------------------------------------------------


class TestRouteConfigGet:
    def test_returns_200(self, client):
        assert client.get("/config").status_code == 200

    def test_shows_field_labels(self, client):
        data = client.get("/config").data
        assert b"Plex Token" in data
        assert b"Plex Player Identifier" in data
        assert b"Assistant Phone Number" in data
        assert b"Radio Stations" in data

    def test_prepopulates_non_password_fields(self, client):
        # PLEX_PLAYER_IDENTIFIER="abc123" in config_file fixture
        assert b"abc123" in client.get("/config").data

    def test_does_not_expose_token_in_html(self, client):
        # PLEX_TOKEN is a password field; its value must not appear in the HTML
        assert b"existingtoken" not in client.get("/config").data

    def test_shows_existing_radio_stations(self, client):
        data = client.get("/config").data
        assert b"KEXP" in data
        assert b"5550903" in data


# ---------------------------------------------------------------------------
# POST /config/env
# ---------------------------------------------------------------------------


class TestRouteUpdateConfigEnv:
    """Tests for the settings form submission."""

    # Minimal valid form: required non-password fields filled, password blank.
    _base = {
        "PLEX_TOKEN": "",           # blank = keep existing
        "PLEX_PLAYER_IDENTIFIER": "player-xyz",
        "PLEX_URL": "http://localhost:32400",
        "ASSISTANT_NUMBER": "5550001",
        "HOOK_SWITCH_PIN": "17",
        "PULSE_SWITCH_PIN": "27",
        "PIPER_BINARY": "/usr/local/bin/piper",
        "PIPER_MODEL": "/usr/local/share/piper/en_US-lessac-medium.onnx",
        "TTS_CACHE_DIR": "/var/cache/hello-operator/tts",
    }

    def _form(self, **overrides):
        return {**self._base, **overrides}

    def test_valid_submission_returns_200(self, client):
        assert client.post("/config/env", data=self._form()).status_code == 200

    def test_blank_password_field_does_not_produce_error(self, client):
        resp = client.post("/config/env", data=self._form(PLEX_TOKEN=""))
        # The error banner only appears on validation failures
        assert b"Please fix the following" not in resp.data

    def test_provided_password_is_written_to_file(self, client, config_file):
        client.post("/config/env", data=self._form(PLEX_TOKEN="brandnewtoken"))
        assert "brandnewtoken" in config_file.read_text()

    def test_missing_required_non_password_field_shows_error(self, client):
        resp = client.post("/config/env", data=self._form(ASSISTANT_NUMBER=""))
        # The error message format is "<Label> is required."
        assert b"is required" in resp.data

    def test_missing_required_field_does_not_write_file(self, client, config_file):
        original = config_file.read_text()
        client.post("/config/env", data=self._form(ASSISTANT_NUMBER=""))
        assert config_file.read_text() == original

    def test_missing_required_field_does_not_call_restart(self, client, monkeypatch):
        restart = Mock(return_value=(True, ""))
        monkeypatch.setattr(wa, "restart_service", restart)
        client.post("/config/env", data=self._form(ASSISTANT_NUMBER=""))
        restart.assert_not_called()

    def test_valid_submission_updates_config_file(self, client, config_file):
        client.post("/config/env", data=self._form(PLEX_URL="http://192.168.1.5:32400"))
        assert "192.168.1.5" in config_file.read_text()

    def test_valid_submission_calls_restart(self, client, monkeypatch):
        restart = Mock(return_value=(True, ""))
        monkeypatch.setattr(wa, "restart_service", restart)
        client.post("/config/env", data=self._form())
        restart.assert_called_once()

    def test_success_message_shown_after_restart(self, client):
        resp = client.post("/config/env", data=self._form())
        assert b"restarted" in resp.data.lower()

    def test_restart_failure_shows_warning_not_error_page(self, client, monkeypatch):
        monkeypatch.setattr(wa, "restart_service", lambda: (False, "unit not found"))
        resp = client.post("/config/env", data=self._form())
        assert resp.status_code == 200
        assert b"restart failed" in resp.data.lower()


# ---------------------------------------------------------------------------
# POST /config/radio
# ---------------------------------------------------------------------------


class TestRouteUpdateRadio:
    _valid = [{"name": "KEXP", "frequency_mhz": 90.3, "phone_number": "5550903"}]

    def test_valid_stations_returns_200_ok(self, client):
        resp = client.post("/config/radio", json=self._valid)
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_valid_stations_written_to_file(self, client, radio_file):
        new = [{"name": "KNKX", "frequency_mhz": 88.5, "phone_number": "5550885"}]
        client.post("/config/radio", json=new)
        assert json.loads(radio_file.read_text())[0]["name"] == "KNKX"

    def test_empty_list_saves_ok(self, client, radio_file):
        resp = client.post("/config/radio", json=[])
        assert resp.status_code == 200
        assert json.loads(radio_file.read_text()) == []

    def test_valid_submission_calls_restart(self, client, monkeypatch):
        restart = Mock(return_value=(True, ""))
        monkeypatch.setattr(wa, "restart_service", restart)
        client.post("/config/radio", json=self._valid)
        restart.assert_called_once()

    def test_phone_number_too_short_returns_422(self, client):
        bad = [{"name": "X", "frequency_mhz": 90.3, "phone_number": "123"}]
        resp = client.post("/config/radio", json=bad)
        assert resp.status_code == 422
        assert resp.get_json()["ok"] is False

    def test_phone_number_too_long_returns_422(self, client):
        bad = [{"name": "X", "frequency_mhz": 90.3, "phone_number": "12345678"}]
        assert client.post("/config/radio", json=bad).status_code == 422

    def test_non_digit_phone_number_returns_422(self, client):
        bad = [{"name": "X", "frequency_mhz": 90.3, "phone_number": "555-090"}]
        assert client.post("/config/radio", json=bad).status_code == 422

    def test_empty_name_returns_422(self, client):
        bad = [{"name": "", "frequency_mhz": 90.3, "phone_number": "5550903"}]
        assert client.post("/config/radio", json=bad).status_code == 422

    def test_non_numeric_frequency_returns_422(self, client):
        bad = [{"name": "X", "frequency_mhz": "fast", "phone_number": "5550903"}]
        assert client.post("/config/radio", json=bad).status_code == 422

    def test_negative_frequency_returns_422(self, client):
        bad = [{"name": "X", "frequency_mhz": -1.0, "phone_number": "5550903"}]
        assert client.post("/config/radio", json=bad).status_code == 422

    def test_non_json_body_returns_400(self, client):
        resp = client.post("/config/radio", data="not json", content_type="text/plain")
        assert resp.status_code == 400

    def test_validation_errors_do_not_write_file(self, client, radio_file):
        original = radio_file.read_text()
        bad = [{"name": "X", "frequency_mhz": 90.3, "phone_number": "123"}]
        client.post("/config/radio", json=bad)
        assert radio_file.read_text() == original

    def test_error_message_identifies_station_number(self, client):
        payload = [
            {"name": "Good", "frequency_mhz": 90.3, "phone_number": "5550903"},
            {"name": "Bad",  "frequency_mhz": 88.5, "phone_number": "123"},
        ]
        data = client.post("/config/radio", json=payload).get_json()
        assert any("Station 2" in e for e in data["errors"])

    def test_restart_failure_still_reports_ok_true(self, client, monkeypatch):
        monkeypatch.setattr(wa, "restart_service", lambda: (False, "failed"))
        resp = client.post("/config/radio", json=self._valid)
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert "Restart failed" in data["message"]


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------


class TestRouteApiStatus:
    def test_returns_200_with_json_content_type(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        assert resp.content_type.startswith("application/json")

    def test_returns_status_field(self, client):
        assert client.get("/api/status").get_json()["status"] == "active"

    def test_reflects_current_service_state(self, client, monkeypatch):
        monkeypatch.setattr(wa, "get_service_status", lambda: "failed")
        assert client.get("/api/status").get_json()["status"] == "failed"


# ---------------------------------------------------------------------------
# POST /service/restart
# ---------------------------------------------------------------------------


class TestRouteServiceRestart:
    def test_success_returns_ok_true(self, client):
        data = client.post("/service/restart").get_json()
        assert data["ok"] is True
        assert data["error"] is None

    def test_failure_returns_ok_false_with_error_text(self, client, monkeypatch):
        monkeypatch.setattr(wa, "restart_service", lambda: (False, "unit not found"))
        data = client.post("/service/restart").get_json()
        assert data["ok"] is False
        assert "unit not found" in data["error"]

    def test_response_includes_current_status(self, client):
        data = client.post("/service/restart").get_json()
        assert "status" in data
