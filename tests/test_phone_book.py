"""Tests for src/phone_book.py."""

import sqlite3
from unittest.mock import patch

import pytest

from src.phone_book import PhoneBook
from src.constants import PHONE_NUMBER_LENGTH, ASSISTANT_NUMBER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def book(tmp_path):
    return PhoneBook(str(tmp_path / "phone.db"))


# Stable test number that is guaranteed != ASSISTANT_NUMBER (default "5550000").
# Used as the pre-seeded collision target in _generate_unique_number tests.
_STABLE_NUMBER = "9876543" if ASSISTANT_NUMBER != "9876543" else "9876542"


# ---------------------------------------------------------------------------
# __init__ / _init_db
# ---------------------------------------------------------------------------


class TestInit:
    def test_creates_phone_book_table(self, tmp_path):
        db = str(tmp_path / "phone.db")
        PhoneBook(db)
        conn = sqlite3.connect(db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "phone_book" in tables

    def test_table_has_required_columns(self, tmp_path):
        db = str(tmp_path / "phone.db")
        PhoneBook(db)
        conn = sqlite3.connect(db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(phone_book)").fetchall()}
        conn.close()
        assert {"media_key", "media_type", "name", "phone_number"} <= cols

    def test_creation_is_idempotent(self, tmp_path):
        db = str(tmp_path / "phone.db")
        PhoneBook(db)
        PhoneBook(db)  # second construction on same file must not raise

    def test_raises_runtime_error_on_bad_path(self):
        with pytest.raises(RuntimeError):
            PhoneBook("/nonexistent_dir/phone.db")

    def test_runtime_error_wraps_sqlite_error(self):
        with pytest.raises(RuntimeError, match="PhoneBook"):
            PhoneBook("/nonexistent_dir/phone.db")


# ---------------------------------------------------------------------------
# _init_db migration
# ---------------------------------------------------------------------------


class TestMigration:
    def _make_old_schema_db(self, db_path: str) -> None:
        """Create a DB with the legacy plex_key column name."""
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE phone_book (
                plex_key     TEXT PRIMARY KEY,
                media_type   TEXT NOT NULL,
                name         TEXT NOT NULL,
                phone_number TEXT NOT NULL UNIQUE
            )
        """)
        conn.commit()
        conn.close()

    def test_renames_plex_key_to_media_key(self, tmp_path):
        db = str(tmp_path / "old.db")
        self._make_old_schema_db(db)
        PhoneBook(db)
        conn = sqlite3.connect(db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(phone_book)").fetchall()]
        conn.close()
        assert "media_key" in cols
        assert "plex_key" not in cols

    def test_migration_preserves_existing_rows(self, tmp_path):
        db = str(tmp_path / "old.db")
        self._make_old_schema_db(db)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO phone_book (plex_key, media_type, name, phone_number) "
            "VALUES ('pl:1', 'playlist', 'Jazz', '1234567')"
        )
        conn.commit()
        conn.close()

        PhoneBook(db)

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT media_key FROM phone_book").fetchone()
        conn.close()
        assert row[0] == "pl:1"

    def test_no_migration_on_fresh_db(self, tmp_path):
        db = str(tmp_path / "fresh.db")
        book = PhoneBook(db)
        conn = sqlite3.connect(db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(phone_book)").fetchall()]
        conn.close()
        assert "media_key" in cols
        assert "plex_key" not in cols

    def test_no_migration_when_media_key_already_present(self, tmp_path):
        db = str(tmp_path / "already.db")
        # Build a DB that has BOTH columns (shouldn't happen, but must be safe)
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE phone_book (
                media_key    TEXT PRIMARY KEY,
                plex_key     TEXT,
                media_type   TEXT NOT NULL,
                name         TEXT NOT NULL,
                phone_number TEXT NOT NULL UNIQUE
            )
        """)
        conn.commit()
        conn.close()
        PhoneBook(db)  # must not raise or alter the schema
        conn = sqlite3.connect(db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(phone_book)").fetchall()]
        conn.close()
        assert "plex_key" in cols   # left untouched


# ---------------------------------------------------------------------------
# _generate_unique_number
# ---------------------------------------------------------------------------


class TestGenerateUniqueNumber:
    def test_returns_string(self, book):
        with book._connect() as conn:
            result = book._generate_unique_number(conn)
        assert isinstance(result, str)

    def test_length_equals_phone_number_length(self, book):
        with book._connect() as conn:
            result = book._generate_unique_number(conn)
        assert len(result) == PHONE_NUMBER_LENGTH

    def test_never_starts_with_zero(self, book):
        with book._connect() as conn:
            for _ in range(20):
                number = book._generate_unique_number(conn)
                assert number[0] != '0', f"Generated number {number!r} starts with 0"

    def test_never_equals_assistant_number(self, book, monkeypatch):
        # Force all candidates to be ASSISTANT_NUMBER → must exhaust attempts
        monkeypatch.setattr("src.phone_book.PHONE_NUMBER_GENERATE_MAX_ATTEMPTS", 3)
        with patch("src.phone_book.random.randint", return_value=int(ASSISTANT_NUMBER)):
            with book._connect() as conn:
                with pytest.raises(RuntimeError):
                    book._generate_unique_number(conn)

    def test_retries_on_collision_with_existing_number(self, book):
        book.seed(_STABLE_NUMBER, "pl:stable", "playlist", "Stable")

        call_count = [0]
        fresh = "2345678" if ASSISTANT_NUMBER != "2345678" else "2345679"

        def controlled_randint(lo, hi):
            call_count[0] += 1
            return int(_STABLE_NUMBER) if call_count[0] == 1 else int(fresh)

        with patch("src.phone_book.random.randint", side_effect=controlled_randint):
            with book._connect() as conn:
                number = book._generate_unique_number(conn)

        assert number == fresh
        assert call_count[0] == 2

    def test_raises_runtime_error_when_space_exhausted(self, book, monkeypatch):
        monkeypatch.setattr("src.phone_book.PHONE_NUMBER_GENERATE_MAX_ATTEMPTS", 1)
        with patch("src.phone_book.random.randint", return_value=int(ASSISTANT_NUMBER)):
            with book._connect() as conn:
                with pytest.raises(RuntimeError, match="exhausted"):
                    book._generate_unique_number(conn)

    def test_result_is_all_digits(self, book):
        with book._connect() as conn:
            result = book._generate_unique_number(conn)
        assert result.isdigit()


# ---------------------------------------------------------------------------
# assign_or_get
# ---------------------------------------------------------------------------


class TestAssignOrGet:
    def test_returns_a_string(self, book):
        result = book.assign_or_get("pl:1", "playlist", "Jazz")
        assert isinstance(result, str)

    def test_returned_number_has_correct_length(self, book):
        result = book.assign_or_get("pl:1", "playlist", "Jazz")
        assert len(result) == PHONE_NUMBER_LENGTH

    def test_returned_number_does_not_start_with_zero(self, book):
        result = book.assign_or_get("pl:1", "playlist", "Jazz")
        assert result[0] != '0'

    def test_same_key_returns_same_number(self, book):
        first = book.assign_or_get("pl:1", "playlist", "Jazz")
        second = book.assign_or_get("pl:1", "playlist", "Jazz")
        assert first == second

    def test_same_key_does_not_generate_new_number(self, book):
        book.assign_or_get("pl:1", "playlist", "Jazz")
        with patch.object(book, "_generate_unique_number") as mock_gen:
            book.assign_or_get("pl:1", "playlist", "Jazz")
        mock_gen.assert_not_called()

    def test_different_keys_get_different_numbers(self, book):
        n1 = book.assign_or_get("pl:1", "playlist", "Jazz")
        n2 = book.assign_or_get("pl:2", "playlist", "Rock")
        assert n1 != n2

    def test_number_is_persisted_across_instances(self, tmp_path):
        db = str(tmp_path / "phone.db")
        book1 = PhoneBook(db)
        number = book1.assign_or_get("pl:1", "playlist", "Jazz")
        book2 = PhoneBook(db)
        assert book2.assign_or_get("pl:1", "playlist", "Jazz") == number

    def test_all_assigned_numbers_are_unique(self, book):
        numbers = [book.assign_or_get(f"pl:{i}", "playlist", f"Item {i}") for i in range(10)]
        assert len(set(numbers)) == 10

    def test_returned_number_is_all_digits(self, book):
        result = book.assign_or_get("pl:1", "playlist", "Jazz")
        assert result.isdigit()


# ---------------------------------------------------------------------------
# lookup_by_media_key
# ---------------------------------------------------------------------------


class TestLookupByMediaKey:
    def test_returns_none_when_not_found(self, book):
        assert book.lookup_by_media_key("pl:missing") is None

    def test_returns_dict_when_found(self, book):
        book.assign_or_get("pl:1", "playlist", "Jazz")
        result = book.lookup_by_media_key("pl:1")
        assert isinstance(result, dict)

    def test_dict_contains_media_key(self, book):
        book.assign_or_get("pl:1", "playlist", "Jazz")
        assert book.lookup_by_media_key("pl:1")["media_key"] == "pl:1"

    def test_dict_contains_media_type(self, book):
        book.assign_or_get("pl:1", "playlist", "Jazz")
        assert book.lookup_by_media_key("pl:1")["media_type"] == "playlist"

    def test_dict_contains_name(self, book):
        book.assign_or_get("pl:1", "playlist", "Jazz")
        assert book.lookup_by_media_key("pl:1")["name"] == "Jazz"

    def test_dict_contains_phone_number(self, book):
        number = book.assign_or_get("pl:1", "playlist", "Jazz")
        assert book.lookup_by_media_key("pl:1")["phone_number"] == number

    def test_lookup_matches_correct_entry(self, book):
        book.assign_or_get("pl:1", "playlist", "Jazz")
        book.assign_or_get("pl:2", "playlist", "Rock")
        result = book.lookup_by_media_key("pl:2")
        assert result["media_key"] == "pl:2"
        assert result["name"] == "Rock"


# ---------------------------------------------------------------------------
# lookup_by_phone_number
# ---------------------------------------------------------------------------


class TestLookupByPhoneNumber:
    def test_returns_none_when_not_found(self, book):
        assert book.lookup_by_phone_number("0000000") is None

    def test_returns_dict_when_found(self, book):
        number = book.assign_or_get("pl:1", "playlist", "Jazz")
        result = book.lookup_by_phone_number(number)
        assert isinstance(result, dict)

    def test_dict_has_all_four_fields(self, book):
        number = book.assign_or_get("pl:1", "playlist", "Jazz")
        result = book.lookup_by_phone_number(number)
        assert {"media_key", "media_type", "name", "phone_number"} <= result.keys()

    def test_dict_contains_correct_media_key(self, book):
        number = book.assign_or_get("pl:1", "playlist", "Jazz")
        assert book.lookup_by_phone_number(number)["media_key"] == "pl:1"

    def test_dict_contains_correct_name(self, book):
        number = book.assign_or_get("pl:1", "playlist", "Jazz")
        assert book.lookup_by_phone_number(number)["name"] == "Jazz"

    def test_dict_contains_correct_media_type(self, book):
        number = book.assign_or_get("pl:1", "playlist", "Jazz")
        assert book.lookup_by_phone_number(number)["media_type"] == "playlist"

    def test_lookup_matches_correct_entry(self, book):
        n1 = book.assign_or_get("pl:1", "playlist", "Jazz")
        n2 = book.assign_or_get("pl:2", "playlist", "Rock")
        assert book.lookup_by_phone_number(n1)["name"] == "Jazz"
        assert book.lookup_by_phone_number(n2)["name"] == "Rock"

    def test_roundtrip_with_assign_or_get(self, book):
        number = book.assign_or_get("pl:1", "playlist", "Jazz")
        result = book.lookup_by_phone_number(number)
        assert result["phone_number"] == number
        assert result["media_key"] == "pl:1"

    def test_seeded_entry_is_retrievable_by_number(self, book):
        book.seed(_STABLE_NUMBER, "radio:90300000.0", "radio", "KEXP")
        result = book.lookup_by_phone_number(_STABLE_NUMBER)
        assert result is not None
        assert result["media_key"] == "radio:90300000.0"


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------


class TestSeed:
    def test_inserts_entry(self, book):
        book.seed(_STABLE_NUMBER, "pl:1", "playlist", "Jazz")
        assert book.lookup_by_phone_number(_STABLE_NUMBER) is not None

    def test_entry_fields_are_correct(self, book):
        book.seed(_STABLE_NUMBER, "pl:1", "playlist", "Jazz")
        result = book.lookup_by_phone_number(_STABLE_NUMBER)
        assert result["media_key"] == "pl:1"
        assert result["media_type"] == "playlist"
        assert result["name"] == "Jazz"
        assert result["phone_number"] == _STABLE_NUMBER

    def test_idempotent_same_args(self, book):
        book.seed(_STABLE_NUMBER, "pl:1", "playlist", "Jazz")
        book.seed(_STABLE_NUMBER, "pl:1", "playlist", "Jazz")
        assert len(book.get_all()) == 1

    def test_skips_silently_when_phone_number_exists(self, book):
        book.seed(_STABLE_NUMBER, "pl:1", "playlist", "Jazz")
        book.seed(_STABLE_NUMBER, "pl:2", "playlist", "Rock")  # same number, different key
        # Original entry unchanged
        result = book.lookup_by_phone_number(_STABLE_NUMBER)
        assert result["media_key"] == "pl:1"

    def test_does_not_overwrite_existing_number_assignment(self, book):
        original = book.assign_or_get("pl:1", "playlist", "Jazz")
        different = "2345678" if ASSISTANT_NUMBER != "2345678" else "2345679"
        # Try to seed a different number for the same media_key
        book.seed(different, "pl:1", "playlist", "Jazz")
        # The original assignment must be intact
        assert book.lookup_by_media_key("pl:1")["phone_number"] == original

    def test_raises_value_error_for_number_starting_with_zero(self, book):
        with pytest.raises(ValueError):
            book.seed("0123456", "pl:1", "playlist", "Jazz")

    def test_raises_value_error_message_mentions_zero(self, book):
        with pytest.raises(ValueError, match="0"):
            book.seed("0000001", "pl:1", "playlist", "Jazz")

    def test_supports_all_media_types(self, book):
        entries = [
            ("1111111", "pl:1",          "playlist", "Playlist"),
            ("2222222", "artist:bach",   "artist",   "Bach"),
            ("3333333", "album:wtc",     "album",    "WTC"),
            ("4444444", "genre:Jazz",    "genre",    "Jazz"),
            ("5555555", "radio:90300000","radio",    "KEXP"),
        ]
        for number, key, mtype, name in entries:
            if number == ASSISTANT_NUMBER:
                continue
            book.seed(number, key, mtype, name)
        stored = {e["phone_number"] for e in book.get_all()}
        for number, *_ in entries:
            if number != ASSISTANT_NUMBER:
                assert number in stored


# ---------------------------------------------------------------------------
# get_all
# ---------------------------------------------------------------------------


class TestGetAll:
    def test_returns_empty_list_when_no_entries(self, book):
        assert book.get_all() == []

    def test_returns_list_of_dicts(self, book):
        book.assign_or_get("pl:1", "playlist", "Jazz")
        result = book.get_all()
        assert isinstance(result, list)
        assert isinstance(result[0], dict)

    def test_returns_one_entry(self, book):
        book.assign_or_get("pl:1", "playlist", "Jazz")
        assert len(book.get_all()) == 1

    def test_returns_all_entries(self, book):
        book.assign_or_get("pl:1", "playlist", "Jazz")
        book.assign_or_get("pl:2", "playlist", "Rock")
        book.assign_or_get("pl:3", "playlist", "Blues")
        assert len(book.get_all()) == 3

    def test_each_dict_has_all_fields(self, book):
        book.assign_or_get("pl:1", "playlist", "Jazz")
        row = book.get_all()[0]
        assert {"media_key", "media_type", "name", "phone_number"} <= row.keys()

    def test_seeded_entries_included(self, book):
        book.seed(_STABLE_NUMBER, "radio:90300000.0", "radio", "KEXP")
        keys = {e["media_key"] for e in book.get_all()}
        assert "radio:90300000.0" in keys

    def test_mixed_assign_and_seed_entries(self, book):
        book.seed(_STABLE_NUMBER, "radio:90300000.0", "radio", "KEXP")
        book.assign_or_get("pl:1", "playlist", "Jazz")
        assert len(book.get_all()) == 2
