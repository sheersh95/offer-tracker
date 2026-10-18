from datetime import UTC, date, datetime

import pytest

from offer_tracker.models import Email, Offer
from offer_tracker.store import OfferStore


@pytest.fixture
def store():
    return OfferStore(":memory:")


@pytest.fixture
def now():
    return datetime(2026, 10, 18, 7, 0, tzinfo=UTC)


def make_offer(**overrides) -> Offer:
    fields = dict(
        store="Nike",
        title="25% off sitewide",
        discount="25% off",
        code="FALL25",
        expires_on=date(2026, 10, 20),
        url="https://example.com/nike",
        email_id="msg-1",
        received_at=datetime(2026, 10, 18, 6, 0, tzinfo=UTC),
    )
    fields.update(overrides)
    return Offer(**fields)


def make_email(**overrides) -> Email:
    fields = dict(
        id="msg-1",
        sender="Nike <news@nike.com>",
        subject="25% off everything this weekend",
        received_at=datetime(2026, 10, 18, 6, 0, tzinfo=UTC),
        body_text="Use code FALL25 for 25% off. Offer ends Sunday.",
    )
    fields.update(overrides)
    return Email(**fields)
