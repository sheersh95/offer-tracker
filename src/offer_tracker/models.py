"""Domain models shared across the pipeline."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class Email(BaseModel):
    """A promotional email as fetched from Gmail."""

    id: str
    sender: str
    subject: str
    received_at: datetime
    body_text: str


class ExtractedOffer(BaseModel):
    """What Claude pulls out of one email. An email can hold several offers."""

    store: str = Field(description="Brand or store name, e.g. 'Nike'")
    title: str = Field(description="Short description of the deal, e.g. '25% off sitewide'")
    discount: str | None = Field(None, description="The discount as written, e.g. '$20 off $100'")
    code: str | None = Field(None, description="Promo code, if one is required")
    expires_on: date | None = Field(None, description="Last valid day, if stated")
    url: str | None = Field(None, description="Link to redeem the offer, if present")


class Offer(ExtractedOffer):
    """An offer as stored, linked back to its source email."""

    id: int | None = None
    email_id: str
    received_at: datetime
