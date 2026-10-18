"""Turn promotional emails into structured offers using Claude."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, TypeAdapter

from .models import Email, ExtractedOffer

# Cheap pre-filter so newsletters and receipts never reach the API.
OFFER_HINTS = re.compile(
    r"(\d+\s?%\s?off|\$\d+\s?off|promo|coupon|code|sale|deal|discount|free shipping|bogo"
    r"|save \$?\d+|expires|ends (today|tonight|soon))",
    re.IGNORECASE,
)

MAX_BODY_CHARS = 20_000

SYSTEM_PROMPT = """\
You extract shopping offers from promotional emails.
Return every distinct offer the email advertises: a discount, a promo code, free shipping, \
or a time-limited deal. Ignore generic marketing with no concrete offer.
Use the store or brand name as it appears to customers. Copy promo codes exactly.
Resolve relative expiry dates ("ends Sunday") against the email's received date and give \
them as YYYY-MM-DD. Leave a field null when the email does not say."""


class _ExtractionResult(BaseModel):
    offers: list[ExtractedOffer]


def looks_like_offer(email: Email) -> bool:
    return bool(OFFER_HINTS.search(f"{email.subject}\n{email.body_text[:5000]}"))


def _schema() -> dict:
    schema = TypeAdapter(_ExtractionResult).json_schema()
    return _close_objects(schema)


def _close_objects(node):
    """Structured outputs require additionalProperties: false and full `required` lists."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
        for value in node.values():
            _close_objects(value)
    elif isinstance(node, list):
        for item in node:
            _close_objects(item)
    return node


class OfferExtractor:
    def __init__(self, client, model: str):
        self._client = client
        self._model = model
        self._schema = _schema()

    def extract(self, email: Email) -> list[ExtractedOffer]:
        if not looks_like_offer(email):
            return []
        user_content = (
            f"From: {email.sender}\n"
            f"Subject: {email.subject}\n"
            f"Received: {email.received_at.date().isoformat()}\n\n"
            f"{email.body_text[:MAX_BODY_CHARS]}"
        )
        response = self._client.beta.messages.create(
            model=self._model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": self._schema},
            },
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason in ("refusal", "max_tokens"):
            return []
        text = next(b.text for b in response.content if b.type == "text")
        return _ExtractionResult.model_validate(json.loads(text)).offers
