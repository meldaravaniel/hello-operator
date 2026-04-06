"""Tests for PhoneBook — phone number registry."""

import re
import pytest
from src.phone_book import PhoneBook
from src.constants import PHONE_NUMBER_LENGTH, ASSISTANT_NUMBER


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


def test_lookup_by_plex_key(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    pb.assign_or_get("/lib/1", "playlist", "My Playlist")
    item = pb.lookup_by_plex_key("/lib/1")
    assert item is not None
    assert item["name"] == "My Playlist"
    assert item["media_type"] == "playlist"


def test_lookup_by_phone_number(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    number = pb.assign_or_get("/lib/1", "playlist", "My Playlist")
    item = pb.lookup_by_phone_number(number)
    assert item is not None
    assert item["plex_key"] == "/lib/1"
    assert item["name"] == "My Playlist"


def test_lookup_missing_key(tmp_phone_book):
    pb = PhoneBook(tmp_phone_book)
    result = pb.lookup_by_plex_key("/lib/does_not_exist")
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
