"""FastAPI dashboard for browsing tracked offers."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .config import Settings
from .digest import templates
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


def create_app(settings: Settings | None = None, offer_store: OfferStore | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = offer_store or OfferStore(settings.db_path)
    app = FastAPI(title="Offer Tracker")

    @app.get("/api/offers")
    def api_offers(store: str | None = None, q: str | None = None) -> list[Offer]:
        return filter_offers(db.active(date.today()), store, q)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(store: str | None = None, q: str | None = None) -> str:
        today = date.today()
        offers = filter_offers(db.active(today), store, q)
        soon = today + timedelta(days=settings.expiring_soon_days)
        return templates.get_template("dashboard.html").render(
            offers=offers,
            stores=db.stores(),
            selected_store=store,
            q=q or "",
            today=today,
            soon=soon,
            with_code=sum(1 for o in offers if o.code),
            expiring=sum(1 for o in offers if o.expires_on and o.expires_on <= soon),
        )

    return app
