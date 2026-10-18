import json
from types import SimpleNamespace

from conftest import make_email

from offer_tracker.extract import OfferExtractor, _schema, looks_like_offer


class FakeMessages:
    def __init__(self, payload, stop_reason="end_turn"):
        self.payload = payload
        self.stop_reason = stop_reason
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=json.dumps(self.payload))],
        )


def fake_client(payload, stop_reason="end_turn"):
    messages = FakeMessages(payload, stop_reason)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_prefilter():
    assert looks_like_offer(make_email())
    assert not looks_like_offer(
        make_email(subject="Your weekly newsletter", body_text="Here is what we wrote this week.")
    )


def test_schema_is_closed_for_structured_outputs():
    schema = _schema()
    offer = schema["$defs"]["ExtractedOffer"]
    assert offer["additionalProperties"] is False
    assert set(offer["required"]) == set(offer["properties"])


def test_extract_parses_offers():
    client, messages = fake_client(
        {
            "offers": [
                {
                    "store": "Nike",
                    "title": "25% off sitewide",
                    "discount": "25% off",
                    "code": "FALL25",
                    "expires_on": "2026-10-19",
                    "url": None,
                }
            ]
        }
    )
    [offer] = OfferExtractor(client, "claude-opus-5-5").extract(make_email())
    assert offer.code == "FALL25"
    assert str(offer.expires_on) == "2026-10-19"
    assert "Received: 2026-10-18" in messages.calls[0]["messages"][0]["content"]


def test_extract_skips_non_offers_without_calling_api():
    client, messages = fake_client({"offers": []})
    email = make_email(subject="Receipt", body_text="Thanks for your order.")
    assert OfferExtractor(client, "m").extract(email) == []
    assert messages.calls == []


def test_refusal_returns_nothing():
    client, _ = fake_client({"offers": []}, stop_reason="refusal")
    assert OfferExtractor(client, "m").extract(make_email()) == []
