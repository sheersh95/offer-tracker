from datetime import date, timedelta

from conftest import make_email, make_offer
from fastapi.testclient import TestClient

from offer_tracker.config import Settings
from offer_tracker.digest import build_digest, render_html
from offer_tracker.models import ExtractedOffer
from offer_tracker.pipeline import sync
from offer_tracker.web import create_app


class StubExtractor:
    def __init__(self, offers=None, fail_ids=()):
        self.offers = offers or [ExtractedOffer(store="Nike", title="25% off", code="FALL25")]
        self.fail_ids = set(fail_ids)

    def extract(self, email):
        if email.id in self.fail_ids:
            raise RuntimeError("boom")
        return self.offers


def test_sync_dedupes_and_skips_processed(store):
    emails = [make_email(id="a"), make_email(id="b")]
    result = sync(emails, StubExtractor(), store)
    assert (result.offers_new, result.offers_duplicate) == (1, 1)
    again = sync(emails, StubExtractor(), store)
    assert again.emails_skipped == 2


def test_sync_retries_failed_emails_next_run(store):
    sync([make_email(id="a")], StubExtractor(fail_ids={"a"}), store)
    assert not store.is_processed("a")


def test_digest_sections(store, now):
    store.upsert(make_offer())  # new today, expires in 2 days
    store.upsert(
        make_offer(
            store="Adidas",
            code="LATER",
            expires_on=date(2026, 11, 30),
            received_at=now - timedelta(days=5),
        )
    )
    store.upsert(make_offer(store="Gap", code="GONE", expires_on=date(2026, 10, 17)))

    digest = build_digest(store, now, expiring_soon_days=3)
    assert [o.code for o in digest.expiring_soon] == ["FALL25"]
    assert list(digest.new_by_store) == ["Nike"]
    assert digest.active_count == 2
    assert [o.store for o in digest.expired_yesterday] == ["Gap"]

    html = render_html(digest, "https://offers.example.com")
    assert "Expiring soon" in html and "FALL25" in html and "Gap" in html


def test_empty_digest(store, now):
    digest = build_digest(store, now)
    assert digest.is_empty
    assert "No new offers today" in render_html(digest)


def test_dashboard_filters(store, tmp_path):
    store.upsert(make_offer(expires_on=None))
    store.upsert(make_offer(store="Adidas", code="KICKS", expires_on=None))
    client = TestClient(create_app(Settings.from_env(), offer_store=store))

    page = client.get("/")
    assert page.status_code == 200
    assert "Nike" in page.text and "Adidas" in page.text

    assert [o["code"] for o in client.get("/api/offers?store=Adidas").json()] == ["KICKS"]
    assert [o["code"] for o in client.get("/api/offers?q=fall").json()] == ["FALL25"]
