"""Settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    credentials_path: Path
    token_path: Path
    gmail_query: str
    digest_to: str | None
    claude_model: str
    expiring_soon_days: int

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.environ.get("OFFER_TRACKER_DATA_DIR", "data"))
        return cls(
            db_path=Path(os.environ.get("OFFER_TRACKER_DB", data_dir / "offers.db")),
            credentials_path=Path(
                os.environ.get("GMAIL_CREDENTIALS", data_dir / "credentials.json")
            ),
            token_path=Path(os.environ.get("GMAIL_TOKEN", data_dir / "token.json")),
            gmail_query=os.environ.get("GMAIL_QUERY", "category:promotions newer_than:1d"),
            digest_to=os.environ.get("DIGEST_TO"),
            claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
            expiring_soon_days=int(os.environ.get("EXPIRING_SOON_DAYS", "3")),
        )
