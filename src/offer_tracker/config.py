"""Settings from environment variables, with a local settings file as a fallback.

The dashboard saves values (API key, digest address) to `<data dir>/settings.json` so they
survive restarts. Environment variables always win, which keeps CI and the CLI unchanged.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

LOCAL_KEYS = {"anthropic_api_key": "ANTHROPIC_API_KEY", "digest_to": "DIGEST_TO"}


def _data_dir() -> Path:
    return Path(os.environ.get("OFFER_TRACKER_DATA_DIR", "data"))


def _local_file(data_dir: Path) -> Path:
    return data_dir / "settings.json"


def load_local(data_dir: Path) -> dict:
    path = _local_file(data_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_local(data_dir: Path, **values: str | None) -> None:
    """Merge values into the local settings file. Empty strings clear a value."""
    current = load_local(data_dir)
    for key, value in values.items():
        if key not in LOCAL_KEYS or value is None:
            continue
        if value.strip():
            current[key] = value.strip()
        else:
            current.pop(key, None)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = _local_file(data_dir)
    path.write_text(json.dumps(current, indent=2))
    path.chmod(0o600)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    credentials_path: Path
    token_path: Path
    gmail_query: str
    digest_to: str | None
    anthropic_api_key: str | None
    claude_model: str
    expiring_soon_days: int

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = _data_dir()
        local = load_local(data_dir)
        return cls(
            data_dir=data_dir,
            db_path=Path(os.environ.get("OFFER_TRACKER_DB", data_dir / "offers.db")),
            credentials_path=Path(
                os.environ.get("GMAIL_CREDENTIALS", data_dir / "credentials.json")
            ),
            token_path=Path(os.environ.get("GMAIL_TOKEN", data_dir / "token.json")),
            gmail_query=os.environ.get("GMAIL_QUERY", "category:promotions newer_than:1d"),
            digest_to=os.environ.get("DIGEST_TO") or local.get("digest_to"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or local.get("anthropic_api_key"),
            claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
            expiring_soon_days=int(os.environ.get("EXPIRING_SOON_DAYS", "3")),
        )
