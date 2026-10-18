"""Build the daily digest from stored offers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from jinja2 import Environment, PackageLoader, select_autoescape

from .models import Offer
from .store import OfferStore

templates = Environment(
    loader=PackageLoader("offer_tracker", "templates"),
    autoescape=select_autoescape(),
)


@dataclass
class Digest:
    day: date
    expiring_soon: list[Offer]
    new_by_store: dict[str, list[Offer]]
    active_count: int
    expired_yesterday: list[Offer] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.expiring_soon or self.new_by_store or self.expired_yesterday)

    @property
    def subject(self) -> str:
        new = sum(len(v) for v in self.new_by_store.values())
        return (
            f"Offers for {self.day:%a %b %-d}: {new} new, {len(self.expiring_soon)} expiring soon"
        )


def build_digest(store: OfferStore, now: datetime, expiring_soon_days: int = 3) -> Digest:
    today = now.date()
    active = store.active(today)
    soon_cutoff = today + timedelta(days=expiring_soon_days)
    expiring_soon = [o for o in active if o.expires_on and o.expires_on <= soon_cutoff]

    new_by_store: dict[str, list[Offer]] = defaultdict(list)
    for offer in store.received_since(now - timedelta(days=1)):
        if offer.expires_on and offer.expires_on < today:
            continue
        new_by_store[offer.store].append(offer)

    return Digest(
        day=today,
        expiring_soon=expiring_soon,
        new_by_store=dict(sorted(new_by_store.items())),
        active_count=len(active),
        expired_yesterday=store.expired_between(today - timedelta(days=1), today),
    )


def render_html(digest: Digest, dashboard_url: str | None = None) -> str:
    return templates.get_template("digest.html").render(d=digest, dashboard_url=dashboard_url)
