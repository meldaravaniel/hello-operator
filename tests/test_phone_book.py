"""Tests for PhoneBook — phone number registry."""

import re
import pytest
from unittest.mock import patch
from src.phone_book import PhoneBook
from src.constants import PHONE_NUMBER_LENGTH, ASSISTANT_NUMBER, PHONE_NUMBER_GENERATE_MAX_ATTEMPTS


def test_assign_new_number(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    number = pb.assign_or_get("/library/artists/1", "artist", "The Beatles")
    assert len(number) == PHONE_NUMBER_LENGTH
    assert number.isdigit()


def test_number_format(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    number = pb.assign_or_get("/library/artists/1", "artist", "The Beatles")
    pattern = rf'^\d{{{PHONE_NUMBER_LENGTH}}}$'
    assert re.match(pattern, number)


def test_number_is_unique(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    numbers = set()
    for i in range(100):
        n = pb.assign_or_get(f"/library/item/{i}", "album", f"Album {i}")
        numbers.add(n)
    assert len(numbers) == 100


def test_lookup_by_media_key(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    pb.assign_or_get("/lib/1", "playlist", "My Playlist")
    item = pb.lookup_by_media_key("/lib/1")
    assert item is not None
    assert item["name"] == "My Playlist"
    assert item["media_type"] == "playlist"


def test_lookup_by_phone_number(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    number = pb.assign_or_get("/lib/1", "playlist", "My Playlist")
    item = pb.lookup_by_phone_number(number)
    assert item is not None
    assert item["media_key"] == "/lib/1"
    assert item["name"] == "My Playlist"


def test_lookup_missing_key(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    result = pb.lookup_by_media_key("/lib/does_not_exist")
    assert result is None


def test_persistence(tmp_phone_book):
    pb1 = PhoneBook(tmp_phone_book)
    number = pb1.assign_or_get("/lib/42", "album", "Dark Side")
    del pb1
    pb2 = PhoneBook(tmp_phone_book)
    item = pb2.lookup_by_phone_number(number)
    assert item is not None
    assert item["name"] == "Dark Side"


def test_no_reassignment(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    first = pb.assign_or_get("/lib/1", "artist", "Radiohead")
    second = pb.assign_or_get("/lib/1", "artist", "Radiohead")
    assert first == second
    assert len(pb.get_all()) == 1


def test_lazy_assignment_on_first_encounter(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    n1 = pb.assign_or_get("/lib/5", "genre", "Jazz")
    n2 = pb.assign_or_get("/lib/5", "genre", "Jazz")
    assert n1 == n2


def test_assistant_number_excluded(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    numbers = set()
    for i in range(200):
        n = pb.assign_or_get(f"/lib/{i}", "album", f"Album {i}")
        numbers.add(n)
    assert ASSISTANT_NUMBER not in numbers


def test_db_unreadable_raises(tmp_path):
    bad_path = str(tmp_path / "nonexistent_dir" / "sub" / "book.db")
    with pytest.raises(Exception):
        PhoneBook(bad_path)


def test_get_all_returns_all_entries(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    pb.assign_or_get("/lib/1", "artist", "Artist A")
    pb.assign_or_get("/lib/2", "artist", "Artist B")
    all_items = pb.get_all()
    assert len(all_items) == 2


def test_generate_unique_number_raises_after_max_attempts(tmp_phone_book):
    """_generate_unique_number raises RuntimeError when all candidates are taken."""
    pb = PhoneBook(tmp_phone_book)
    # Patch random.randint so every candidate is always the same "taken" number,
    # simulating a full number space after PHONE_NUMBER_GENERATE_MAX_ATTEMPTS tries.
    import sqlite3
    with pb._connect() as conn:
        conn.execute(
            "INSERT INTO phone_book (media_key, media_type, name, phone_number) VALUES (?, ?, ?, ?)",
            ("/taken/1", "artist", "Taken", "1234567")
        )
    with patch("src.phone_book.random.randint", return_value=1234567):
        with pytest.raises(RuntimeError, match="Phone book number space exhausted"):
            pb.assign_or_get("/lib/new", "artist", "New Artist")


def test_phone_number_generate_max_attempts_constant_exists():
    """PHONE_NUMBER_GENERATE_MAX_ATTEMPTS is defined in constants."""
    assert isinstance(PHONE_NUMBER_GENERATE_MAX_ATTEMPTS, int)
    assert PHONE_NUMBER_GENERATE_MAX_ATTEMPTS > 0


# ---------------------------------------------------------------------------
# seed() tests
# ---------------------------------------------------------------------------

def test_seed_inserts_entry(tmp_phone_book):
    """seed() inserts an entry retrievable by lookup_by_phone_number."""
    pb = PhoneBook(tmp_phone_book)
    pb.seed("5550903", "radio:90300000.0", "radio", "KEXP")
    entry = pb.lookup_by_phone_number("5550903")
    assert entry == {
        "media_key": "radio:90300000.0",
        "media_type": "radio",
        "name": "KEXP",
        "phone_number": "5550903",
    }


def test_seed_idempotent(tmp_phone_book):
    """Calling seed() twice with identical args leaves exactly one entry."""
    pb = PhoneBook(tmp_phone_book)
    pb.seed("5550903", "radio:90300000.0", "radio", "KEXP")
    pb.seed("5550903", "radio:90300000.0", "radio", "KEXP")
    all_entries = pb.get_all()
    assert len(all_entries) == 1


def test_seed_skips_if_phone_number_taken(tmp_phone_book):
    """seed() with a phone number already taken does not overwrite the existing entry."""
    pb = PhoneBook(tmp_phone_book)
    pb.seed("5550903", "radio:A", "radio", "Station A")
    pb.seed("5550903", "radio:B", "radio", "Station B")
    entry = pb.lookup_by_phone_number("5550903")
    assert entry["media_key"] == "radio:A"


def test_seed_skips_if_plex_key_already_assigned(tmp_phone_book):
    """seed() does not raise and does not create a second row when plex_key already has a number."""
    pb = PhoneBook(tmp_phone_book)
    pb.assign_or_get("radio:90300000.0", "radio", "KEXP")
    pb.seed("5550903", "radio:90300000.0", "radio", "KEXP")
    all_entries = pb.get_all()
    assert len(all_entries) == 1


# ---------------------------------------------------------------------------
# CHECK constraint tests
# ---------------------------------------------------------------------------

def test_invalid_media_type_rejected(tmp_phone_book):
    """Inserting a row with an invalid media_type raises sqlite3.IntegrityError."""
    import sqlite3
    pb = PhoneBook(tmp_phone_book)
    with pb._connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO phone_book (media_key, media_type, name, phone_number) VALUES (?, ?, ?, ?)",
                ("/k/1", "track", "Name", "5551234")
            )


def test_valid_media_types_accepted(tmp_phone_book):
    """Each valid media_type value inserts without error."""
    import sqlite3
    pb = PhoneBook(tmp_phone_book)
    valid_types = ["playlist", "artist", "album", "genre", "radio"]
    with pb._connect() as conn:
        for i, media_type in enumerate(valid_types):
            conn.execute(
                "INSERT INTO phone_book (media_key, media_type, name, phone_number) VALUES (?, ?, ?, ?)",
                (f"/k/{i}", media_type, f"Name {i}", f"555000{i}")
            )


# ---------------------------------------------------------------------------
# Bug regression: seed() silently drops entry when media_key already exists
# ---------------------------------------------------------------------------

def test_seed_logs_warning_when_media_key_already_assigned(tmp_phone_book, caplog):
    """seed() must log a warning when INSERT OR IGNORE silently drops the entry.

    If assign_or_get() has already given a media_key a random phone number, a
    subsequent seed() call for that media_key finds the phone_number slot free
    but the INSERT OR IGNORE silently fails on the media_key PRIMARY KEY
    conflict.  The desired vanity number is never registered, and without a
    warning the operator has no way to know the seed was ineffective.
    """
    import logging
    pb = PhoneBook(tmp_phone_book)

    # Assign a random number to the media_key before the seed runs
    pb.assign_or_get("radio:90300000.0", "radio", "KEXP")

    # seed() with the desired phone number — INSERT will silently fail
    with caplog.at_level(logging.WARNING, logger="src.phone_book"):
        pb.seed("5550903", "radio:90300000.0", "radio", "KEXP")

    assert any("radio:90300000.0" in record.message for record in caplog.records), (
        "seed() should emit a warning when the media_key already has a phone number "
        "and the seeded entry is silently dropped, but no warning was logged."
    )
