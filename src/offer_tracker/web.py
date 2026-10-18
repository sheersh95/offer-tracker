"""FastAPI dashboard: browse offers and run every step (setup, sync, digest) with buttons."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import actions
from .config import Settings, save_local
from .digest import templates
from .jobs import JobBusy, JobRunner
from .models import Offer
from .store import OfferStore


def filter_offers(offers: list[Offer], store: str | None, q: str | None) -> list[Offer]:
    if store:
        offers = [o for o in offers if o.store == store]
    if q:
        needle = q.lower()
        offers = [
            o
            for o in offers
            if needle in f"{o.store} {o.title} {o.discount or ''} {o.code or ''}".lower()
        ]
    return offers


async def require_json(request: Request) -> None:
    """Only accept JSON posts. Browsers can't send these cross-site without a CORS preflight,
    so another website can't trigger a sync or send email through your local dashboard."""
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Send a JSON body")


class SettingsUpdate(BaseModel):
    anthropic_api_key: str | None = None
    digest_to: str | None = None
    credentials_json: str | None = None


class SyncRequest(BaseModel):
    days: int = Field(7, ge=1, le=365)
    limit: int = Field(50, ge=1, le=1000)
    query: str | None = None


class SendRequest(BaseModel):
    to: str | None = None


def create_app(
    load_settings: Callable[[], Settings] = Settings.from_env,
    offer_store: OfferStore | None = None,
    services: actions.Services | None = None,
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    services = services or actions.Services()
    db = offer_store or OfferStore(load_settings().db_path)
    jobs = JobRunner(actions.friendly_error)
    app = FastAPI(title="Offer Tracker")
    if allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    def status() -> dict:
        settings = load_settings()
        return {
            "credentials": settings.credentials_path.exists(),
            "gmail_connected": settings.token_path.exists(),
            "api_key": bool(settings.anthropic_api_key),
            "digest_to": settings.digest_to,
            "job": jobs.state.to_dict(),
        }

    def start(name: str, fn) -> dict:
        try:
            return jobs.start(name, fn).to_dict()
        except JobBusy as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/status")
    def api_status() -> dict:
        return status()

    @app.get("/api/job")
    def api_job() -> dict:
        return jobs.state.to_dict()

    @app.get("/api/offers")
    def api_offers(store: str | None = None, q: str | None = None) -> list[Offer]:
        return filter_offers(db.active(date.today()), store, q)

    @app.post("/api/settings", dependencies=[Depends(require_json)])
    def api_settings(body: SettingsUpdate) -> dict:
        settings = load_settings()
        if body.credentials_json is not None:
            try:
                parsed = json.loads(body.credentials_json)
            except json.JSONDecodeError as exc:
                raise HTTPException(400, "That isn't valid JSON") from exc
            if not isinstance(parsed, dict) or not ({"installed", "web"} & parsed.keys()):
                raise HTTPException(
                    400, "This doesn't look like a Google OAuth client file (Desktop app)"
                )
            settings.credentials_path.parent.mkdir(parents=True, exist_ok=True)
            settings.credentials_path.write_text(json.dumps(parsed, indent=2))
            settings.credentials_path.chmod(0o600)
        save_local(
            settings.data_dir, anthropic_api_key=body.anthropic_api_key, digest_to=body.digest_to
        )
        return status()

    @app.post("/api/actions/connect-gmail", dependencies=[Depends(require_json)])
    def api_connect() -> dict:
        settings = load_settings()
        if not settings.credentials_path.exists():
            raise HTTPException(400, "Add your Google credentials file first")

        def run(progress):
            progress("Finish signing in in the browser tab that just opened…")
            return actions.connect_gmail(settings, services)

        return start("Connect Gmail", run)

    @app.post("/api/actions/sync", dependencies=[Depends(require_json)])
    def api_sync(body: SyncRequest) -> dict:
        settings = load_settings()
        if not settings.token_path.exists():
            raise HTTPException(400, "Connect Gmail first")
        if not settings.anthropic_api_key:
            raise HTTPException(400, "Add your Claude API key first")
        query = body.query or f"category:promotions newer_than:{body.days}d"

        def run(progress):
            return actions.sync_offers(
                settings, db, services, query, body.limit, progress
            ).summary()

        return start("Sync", run)

    @app.post("/api/actions/send-digest", dependencies=[Depends(require_json)])
    def api_send(body: SendRequest) -> dict:
        settings = load_settings()
        if not settings.token_path.exists():
            raise HTTPException(400, "Connect Gmail first")
        to = body.to or settings.digest_to
        if not to:
            raise HTTPException(400, "Add an email address for the digest first")
        return start(
            "Send digest", lambda progress: actions.send_digest(settings, db, services, to)
        )

    @app.get("/digest", response_class=HTMLResponse)
    def digest_preview() -> str:
        return actions.make_digest(load_settings(), db)[1]

    @app.get("/", response_class=HTMLResponse)
    def dashboard(store: str | None = None, q: str | None = None) -> str:
        settings = load_settings()
        today = date.today()
        active = db.active(today)
        offers = filter_offers(active, store, q)
        soon = today + timedelta(days=settings.expiring_soon_days)
        return templates.get_template("dashboard.html").render(
            offers=offers,
            stores=sorted({o.store for o in active}),
            selected_store=store,
            q=q or "",
            today=today,
            soon=soon,
            with_code=sum(1 for o in offers if o.code),
            expiring=sum(1 for o in offers if o.expires_on and o.expires_on <= soon),
            status=status(),
        )

    return app
