"""Thin wrapper around the Gmail API: read promotions, send the digest."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from bs4 import BeautifulSoup

from .models import Email

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def load_credentials(credentials_path: Path, token_path: Path, interactive: bool = False):
    """Load saved OAuth credentials, refreshing or running the browser flow as needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif interactive:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        creds = flow.run_local_server(port=0)
    else:
        raise RuntimeError("No valid Gmail token. Run `offer-tracker auth` first.")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return creds


class GmailClient:
    def __init__(self, creds):
        from googleapiclient.discovery import build

        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def search(self, query: str, limit: int = 100) -> Iterator[Email]:
        users = self._service.users()
        request = users.messages().list(userId="me", q=query, maxResults=min(limit, 100))
        seen = 0
        while request is not None and seen < limit:
            response = request.execute()
            for ref in response.get("messages", []):
                msg = users.messages().get(userId="me", id=ref["id"], format="full").execute()
                yield parse_message(msg)
                seen += 1
                if seen >= limit:
                    return
            request = users.messages().list_next(request, response)

    def send_html(self, to: str, subject: str, html: str) -> None:
        mime = MIMEMultipart("alternative")
        mime["To"] = to
        mime["Subject"] = subject
        mime.attach(MIMEText(html, "html"))
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        self._service.users().messages().send(userId="me", body={"raw": raw}).execute()


def parse_message(msg: dict) -> Email:
    """Turn a Gmail API `format=full` message into an Email."""
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    received_at = datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000, tz=UTC)
    return Email(
        id=msg["id"],
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        received_at=received_at,
        body_text=_extract_text(payload),
    )


def _extract_text(payload: dict) -> str:
    """Prefer text/plain; fall back to text/html stripped of markup."""
    plain, html = [], []
    stack = [payload]
    while stack:
        part = stack.pop()
        stack.extend(part.get("parts", []))
        data = part.get("body", {}).get("data")
        if not data:
            continue
        text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        if part.get("mimeType") == "text/plain":
            plain.append(text)
        elif part.get("mimeType") == "text/html":
            html.append(text)
    if plain:
        return "\n".join(plain).strip()
    soup = BeautifulSoup("\n".join(html), "html.parser")
    return soup.get_text(" ", strip=True)
