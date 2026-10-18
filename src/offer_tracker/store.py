"""SQLite storage for offers, with de-duplication."""

from __future__ import annotations

import functools
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

from .models import ExtractedOffer, Offer

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store TEXT NOT NULL,
    title TEXT NOT NULL,
    discount TEXT,
    code TEXT,
    expires_on TEXT,
    url TEXT,
    email_id TEXT NOT NULL,
    received_at TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS processed_emails (
    email_id TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL
);
"""


def dedupe_key(offer: ExtractedOffer) -> str:
    """Same store + same code (or same title when there is no code) is the same offer."""
    store = offer.store.strip().lower()
    ident = (offer.code or offer.title).strip().lower()
    return f"{store}|{ident}"


def _locked(method):
    """The dashboard reads while a background sync writes; serialize access to the connection."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class OfferStore:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    @_locked
    def is_processed(self, email_id: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM processed_emails WHERE email_id = ?", (email_id,)
        ).fetchone()
        return row is not None

    @_locked
    def mark_processed(self, email_id: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO processed_emails VALUES (?, ?)",
            (email_id, datetime.now().isoformat()),
        )
        self._db.commit()

    @_locked
    def upsert(self, offer: Offer) -> bool:
        """Insert an offer. Returns False when it duplicates one already stored.

        A duplicate still updates the expiry when the newer email gives a later date.
        """
        key = dedupe_key(offer)
        expires = offer.expires_on.isoformat() if offer.expires_on else None
        existing = self._db.execute(
            "SELECT id, expires_on FROM offers WHERE dedupe_key = ?", (key,)
        ).fetchone()
        if existing:
            if expires and (existing["expires_on"] is None or expires > existing["expires_on"]):
                self._db.execute(
                    "UPDATE offers SET expires_on = ? WHERE id = ?", (expires, existing["id"])
                )
                self._db.commit()
            return False
        self._db.execute(
            """INSERT INTO offers
               (store, title, discount, code, expires_on, url, email_id, received_at, dedupe_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                offer.store.strip(),
                offer.title,
                offer.discount,
                offer.code,
                expires,
                offer.url,
                offer.email_id,
                offer.received_at.isoformat(),
                key,
            ),
        )
        self._db.commit()
        return True

    @_locked
    def active(self, today: date) -> list[Offer]:
        rows = self._db.execute(
            """SELECT * FROM offers
               WHERE expires_on IS NULL OR expires_on >= ?
               ORDER BY COALESCE(expires_on, '9999-12-31'), store""",
            (today.isoformat(),),
        ).fetchall()
        return [_row_to_offer(r) for r in rows]

    @_locked
    def expired_between(self, start: date, end: date) -> list[Offer]:
        """Offers whose last valid day falls in [start, end)."""
        rows = self._db.execute(
            "SELECT * FROM offers WHERE expires_on >= ? AND expires_on < ? ORDER BY store",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [_row_to_offer(r) for r in rows]

    @_locked
    def received_since(self, since: datetime) -> list[Offer]:
        rows = self._db.execute(
            "SELECT * FROM offers WHERE received_at >= ? ORDER BY store, title",
            (since.isoformat(),),
        ).fetchall()
        return [_row_to_offer(r) for r in rows]

    @_locked
    def stores(self) -> list[str]:
        return [r[0] for r in self._db.execute("SELECT DISTINCT store FROM offers ORDER BY store")]


def _row_to_offer(row: sqlite3.Row) -> Offer:
    return Offer(
        id=row["id"],
        store=row["store"],
        title=row["title"],
        discount=row["discount"],
        code=row["code"],
        expires_on=date.fromisoformat(row["expires_on"]) if row["expires_on"] else None,
        url=row["url"],
        email_id=row["email_id"],
        received_at=datetime.fromisoformat(row["received_at"]),
    )
