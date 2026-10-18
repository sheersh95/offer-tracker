from datetime import date, datetime, timedelta

from conftest import make_offer


def test_insert_and_list_active(store):
    assert store.upsert(make_offer())
    active = store.active(date(2026, 10, 18))
    assert [o.code for o in active] == ["FALL25"]


def test_duplicate_code_is_merged_and_keeps_later_expiry(store):
    assert store.upsert(make_offer())
    assert not store.upsert(make_offer(email_id="msg-2", expires_on=date(2026, 10, 25)))
    [offer] = store.active(date(2026, 10, 18))
    assert offer.expires_on == date(2026, 10, 25)


def test_dedupe_ignores_case_and_whitespace(store):
    store.upsert(make_offer())
    assert not store.upsert(make_offer(store=" nike ", code="fall25"))


def test_offers_without_code_dedupe_on_title(store):
    assert store.upsert(make_offer(code=None, title="Free shipping"))
    assert store.upsert(make_offer(code=None, title="Buy one get one"))
    assert not store.upsert(make_offer(code=None, title="free shipping"))


def test_expired_offers_are_not_active(store):
    store.upsert(make_offer(expires_on=date(2026, 10, 17)))
    store.upsert(make_offer(code="NOEND", expires_on=None))
    assert [o.code for o in store.active(date(2026, 10, 18))] == ["NOEND"]


def test_expired_between(store):
    store.upsert(make_offer(expires_on=date(2026, 10, 17)))
    assert len(store.expired_between(date(2026, 10, 17), date(2026, 10, 18))) == 1


def test_processed_tracking(store):
    assert not store.is_processed("msg-1")
    store.mark_processed("msg-1")
    assert store.is_processed("msg-1")


def test_received_since(store, now):
    store.upsert(make_offer(received_at=now - timedelta(hours=2)))
    store.upsert(make_offer(code="OLD", received_at=now - timedelta(days=3)))
    assert [o.code for o in store.received_since(now - timedelta(days=1))] == ["FALL25"]
    assert isinstance(store.received_since(datetime.min)[0].received_at, datetime)
