"""Command-line entry point: `offer-tracker auth | sync | digest | serve`."""

from __future__ import annotations

import argparse
import logging

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
    serve_p = sub.add_parser("serve", help="Run the dashboard (and open it in your browser)")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--no-browser", action="store_true", help="Don't open a browser tab")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings.from_env()

    from .actions import Services, connect_gmail, make_digest, send_digest, sync_offers

    services = Services()

    if args.command == "auth":
        print(connect_gmail(settings, services), f"(token saved to {settings.token_path})")

    elif args.command == "sync":
        from .store import OfferStore

        store = OfferStore(settings.db_path)
        print(sync_offers(settings, store, services, args.query, args.limit).summary())

    elif args.command == "digest":
        from .store import OfferStore

        store = OfferStore(settings.db_path)
        digest, html = make_digest(settings, store)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"Wrote {args.out}")
        if args.send:
            if not settings.digest_to:
                parser.error("Set DIGEST_TO to send the digest")
            print(send_digest(settings, store, services))
        if not (args.out or args.send):
            print(digest.subject)

    elif args.command == "serve":
        import uvicorn

        from .web import create_app

        url = f"http://{args.host}:{args.port}"
        if not args.no_browser:
            import threading
            import webbrowser

            threading.Timer(1.0, webbrowser.open, args=(url,)).start()
        print(f"Dashboard running at {url} (Ctrl+C to stop)")
        app = create_app(allowed_hosts=[args.host, "localhost", "127.0.0.1"])
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
