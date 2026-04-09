### F-22 · PhoneBook.seed() for pre-configured entries

**Background**
Radio stations have user-assigned 7-digit phone numbers baked into `radio_stations.json` rather than auto-generated. The current `PhoneBook` only supports lazy auto-generation via `assign_or_get()`. A `seed()` method is needed to insert entries with caller-specified phone numbers at startup, without overwriting existing assignments.

**Changes required**

In `src/phone_book.py`, add:

```python
def seed(self, phone_number: str, plex_key: str, media_type: str, name: str) -> None:
    """Insert a pre-configured entry if the phone number is not already present.

    Idempotent: silently skips if phone_number or plex_key already exists.
    """
    with self._connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM phone_book WHERE phone_number = ?", (phone_number,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT OR IGNORE INTO phone_book "
                "(plex_key, media_type, name, phone_number) VALUES (?, ?, ?, ?)",
                (plex_key, media_type, name, phone_number)
            )
```

`INSERT OR IGNORE` handles the case where `plex_key` is already the primary key (prevents duplicate-key error on repeated startup). The outer `SELECT` guard prevents the phone number from being overwritten if it was somehow already assigned to a different entry.

**Acceptance criteria**
- `seed("5550903", "radio:90300000.0", "radio", "KEXP")` inserts an entry retrievable by `lookup_by_phone_number("5550903")`.
- Calling `seed()` twice with the same `phone_number` leaves exactly one entry in the database.
- Calling `seed()` with a `phone_number` already taken by a different `plex_key` does not overwrite the existing entry.
- All existing `test_phone_book.py` tests pass unchanged.

**Testable outcome**
New tests in `tests/test_phone_book.py`:
- `test_seed_inserts_entry` — seed `"5550903"` with key `"radio:90300000.0"` and name `"KEXP"`; `lookup_by_phone_number("5550903")` returns `{"name": "KEXP", "plex_key": "radio:90300000.0", "media_type": "radio", "phone_number": "5550903"}`.
- `test_seed_idempotent` — call `seed()` twice with identical args; `get_all()` returns exactly one entry.
- `test_seed_skips_if_phone_number_taken` — seed `"5550903"` for `"radio:A"`; then seed `"5550903"` again for `"radio:B"`; `lookup_by_phone_number("5550903")["plex_key"]` is still `"radio:A"`.
- `test_seed_skips_if_plex_key_already_assigned` — `assign_or_get("radio:90300000.0", "radio", "KEXP")` generates a number; then `seed("5550903", "radio:90300000.0", "radio", "KEXP")` does not raise and does not create a second row.
