"""Command-line entry point: `offer-tracker auth | sync | digest | serve`."""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime

from .config import Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="offer-tracker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("auth", help="Sign in to Gmail and save a token")
    sync_p = sub.add_parser("sync", help="Fetch new promotions and extract offers")
    sync_p.add_argument("--query", help="Gmail search query (overrides GMAIL_QUERY)")
    sync_p.add_argument("--limit", type=int, default=200)
    digest_p = sub.add_parser("digest", help="Build the daily digest")
    digest_p.add_argument("--send", action="store_true", help="Email it to DIGEST_TO")
    digest_p.add_argument("--out", help="Write the HTML to this file")
    serve_p = sub.add_parser("serve", help="Run the dashboard")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings.from_env()

    if args.command == "auth":
        from .gmail import load_credentials

        load_credentials(settings.credentials_path, settings.token_path, interactive=True)
        print(f"Saved token to {settings.token_path}")

    elif args.command == "sync":
        import anthropic

        from .extract import OfferExtractor
        from .gmail import GmailClient, load_credentials
        from .pipeline import sync
        from .store import OfferStore

        gmail = GmailClient(load_credentials(settings.credentials_path, settings.token_path))
        extractor = OfferExtractor(anthropic.Anthropic(), settings.claude_model)
        store = OfferStore(settings.db_path)
        result = sync(
            gmail.search(args.query or settings.gmail_query, args.limit), extractor, store
        )
        print(
            f"Checked {result.emails_seen} emails: {result.offers_new} new offers, "
            f"{result.offers_duplicate} duplicates, {result.emails_skipped} already processed"
        )

    elif args.command == "digest":
        from .digest import build_digest, render_html
        from .store import OfferStore

        store = OfferStore(settings.db_path)
        digest = build_digest(store, datetime.now(UTC), settings.expiring_soon_days)
        html = render_html(digest, os.environ.get("DASHBOARD_URL"))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"Wrote {args.out}")
        if args.send:
            if not settings.digest_to:
                parser.error("Set DIGEST_TO to send the digest")
            from .gmail import GmailClient, load_credentials

            gmail = GmailClient(load_credentials(settings.credentials_path, settings.token_path))
            gmail.send_html(settings.digest_to, digest.subject, html)
            print(f"Sent digest to {settings.digest_to}")
        if not (args.out or args.send):
            print(digest.subject)

    elif args.command == "serve":
        import uvicorn

        from .web import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
