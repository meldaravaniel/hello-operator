"""Phone number registry — maps media keys to 7-digit phone numbers."""

import logging
import random
import sqlite3
from typing import Optional

from src.constants import PHONE_NUMBER_LENGTH, PHONE_NUMBER_GENERATE_MAX_ATTEMPTS, ASSISTANT_NUMBER

logger = logging.getLogger(__name__)


class PhoneBook:
    """Persistent mapping of media keys to auto-generated phone numbers."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS phone_book (
                        media_key    TEXT PRIMARY KEY,
                        media_type   TEXT NOT NULL CHECK(media_type IN ('playlist','artist','album','genre','radio')),
                        name         TEXT NOT NULL,
                        phone_number TEXT NOT NULL UNIQUE
                    )
                """)
                # Migrate: rename plex_key column → media_key on existing databases
                cols = [row[1] for row in conn.execute("PRAGMA table_info(phone_book)").fetchall()]
                if 'plex_key' in cols and 'media_key' not in cols:
                    conn.execute("ALTER TABLE phone_book RENAME COLUMN plex_key TO media_key")
        except sqlite3.OperationalError as e:
            raise RuntimeError(f"PhoneBook: cannot open database at {self._db_path!r}: {e}") from e

    def _generate_unique_number(self, conn: sqlite3.Connection) -> str:
        """Generate a random PHONE_NUMBER_LENGTH-digit number not already in use.

        Numbers never start with 0 (reserved for the operator shortcut) and never
        equal ASSISTANT_NUMBER.  Raises RuntimeError if a unique number cannot be
        found within PHONE_NUMBER_GENERATE_MAX_ATTEMPTS iterations.
        """
        min_val = 10 ** (PHONE_NUMBER_LENGTH - 1)  # e.g. 1000000 — already no leading zero
        max_val = (10 ** PHONE_NUMBER_LENGTH) - 1
        for _ in range(PHONE_NUMBER_GENERATE_MAX_ATTEMPTS):
            candidate = str(random.randint(min_val, max_val))
            if candidate == ASSISTANT_NUMBER:
                continue
            if candidate[0] == '0':  # defensive; min_val already prevents this
                continue
            exists = conn.execute(
                "SELECT 1 FROM phone_book WHERE phone_number = ?", (candidate,)
            ).fetchone()
            if not exists:
                return candidate
        raise RuntimeError("Phone book number space exhausted")

    def assign_or_get(self, media_key: str, media_type: str, name: str) -> str:
        """Return existing phone number for media_key, or assign a new one."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT phone_number FROM phone_book WHERE media_key = ?", (media_key,)
            ).fetchone()
            if row:
                return row["phone_number"]
            number = self._generate_unique_number(conn)
            conn.execute(
                "INSERT INTO phone_book (media_key, media_type, name, phone_number) VALUES (?, ?, ?, ?)",
                (media_key, media_type, name, number)
            )
            return number

    def lookup_by_media_key(self, media_key: str) -> Optional[dict]:
        """Return dict with media_key, media_type, name, phone_number or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT media_key, media_type, name, phone_number FROM phone_book WHERE media_key = ?",
                (media_key,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def lookup_by_phone_number(self, phone_number: str) -> Optional[dict]:
        """Return dict with media_key, media_type, name, phone_number or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT media_key, media_type, name, phone_number FROM phone_book WHERE phone_number = ?",
                (phone_number,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def seed(self, phone_number: str, media_key: str, media_type: str, name: str) -> None:
        """Insert a pre-configured entry if the phone number is not already present.

        Phone numbers must not start with 0 (reserved for the operator shortcut).
        Idempotent: silently skips if phone_number or media_key already exists.
        """
        if phone_number.startswith('0'):
            raise ValueError(
                f"Phone number {phone_number!r} must not start with 0 "
                "(0 is reserved for the operator shortcut)."
            )
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM phone_book WHERE phone_number = ?", (phone_number,)
            ).fetchone()
            if not exists:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO phone_book "
                    "(media_key, media_type, name, phone_number) VALUES (?, ?, ?, ?)",
                    (media_key, media_type, name, phone_number)
                )
                if cursor.rowcount == 0:
                    logger.warning(
                        "seed(): phone_number %s for media_key %r was not registered "
                        "— media_key is already assigned a different number",
                        phone_number, media_key
                    )

    def get_all(self) -> list:
        """Return all entries as a list of dicts."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT media_key, media_type, name, phone_number FROM phone_book"
            ).fetchall()
        return [dict(r) for r in rows]
