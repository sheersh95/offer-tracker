"""The app's operations, shared by the CLI and the dashboard.

Gmail and Claude clients are created through `Services` so tests can swap in fakes.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .config import Settings
from .digest import Digest, build_digest, render_html
from .pipeline import SyncResult, sync
from .store import OfferStore


def _real_gmail(settings: Settings):
    from .gmail import GmailClient, load_credentials

    return GmailClient(load_credentials(settings.credentials_path, settings.token_path))


def _real_extractor(settings: Settings):
    import anthropic

    from .extract import OfferExtractor

    return OfferExtractor(
        anthropic.Anthropic(api_key=settings.anthropic_api_key), settings.claude_model
    )


def _real_authorize(settings: Settings) -> None:
    from .gmail import load_credentials

    load_credentials(settings.credentials_path, settings.token_path, interactive=True)


@dataclass
class Services:
    gmail: Callable = _real_gmail
    extractor: Callable = _real_extractor
    authorize: Callable = _real_authorize


def connect_gmail(settings: Settings, services: Services) -> str:
    if not settings.credentials_path.exists():
        raise FileNotFoundError(f"Add your Google OAuth client file at {settings.credentials_path}")
    services.authorize(settings)
    return "Gmail connected"


def sync_offers(
    settings: Settings,
    store: OfferStore,
    services: Services,
    query: str | None = None,
    limit: int = 200,
    progress: Callable[[str], None] | None = None,
) -> SyncResult:
    gmail = services.gmail(settings)
    extractor = services.extractor(settings)

    def report(result: SyncResult) -> None:
        if progress:
            progress(f"Reading email {result.emails_seen} of up to {limit}…")

    emails = gmail.search(query or settings.gmail_query, limit)
    return sync(emails, extractor, store, report, fatal=_fatal_api_errors())


def _fatal_api_errors() -> tuple[type[BaseException], ...]:
    try:
        import anthropic
    except ImportError:
        return ()
    return (anthropic.AuthenticationError, anthropic.PermissionDeniedError)


def friendly_error(exc: BaseException) -> str:
    """Turn the errors people actually hit into a next step."""
    name = type(exc).__name__
    text = str(exc)
    if "invalid_client" in text:
        return "Google rejected the credentials file. Paste a fresh one in Setup, then reconnect."
    if name == "RefreshError" or "invalid_grant" in text:
        return "Gmail access expired or was revoked. Click Reconnect Gmail."
    if name == "AuthenticationError":
        return "Claude rejected the API key. Paste a valid key in Setup."
    if "accessNotConfigured" in text or "has not been used in project" in text:
        return "The Gmail API is turned off for your Google Cloud project. Enable it, then retry."
    if isinstance(exc, FileNotFoundError | ValueError):
        return text
    return f"{name}: {text}"


def make_digest(settings: Settings, store: OfferStore) -> tuple[Digest, str]:
    digest = build_digest(store, datetime.now(UTC), settings.expiring_soon_days)
    return digest, render_html(digest, os.environ.get("DASHBOARD_URL"))


def send_digest(
    settings: Settings, store: OfferStore, services: Services, to: str | None = None
) -> str:
    to = to or settings.digest_to
    if not to:
        raise ValueError("Set an address to send the digest to")
    digest, html = make_digest(settings, store)
    services.gmail(settings).send_html(to, digest.subject, html)
    return f"Sent “{digest.subject}” to {to}"
