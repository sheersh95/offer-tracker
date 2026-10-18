"""Fetch → extract → store."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from .extract import OfferExtractor
from .models import Email, Offer
from .store import OfferStore

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    emails_seen: int = 0
    emails_skipped: int = 0
    offers_new: int = 0
    offers_duplicate: int = 0


def sync(emails: Iterable[Email], extractor: OfferExtractor, store: OfferStore) -> SyncResult:
    result = SyncResult()
    for email in emails:
        result.emails_seen += 1
        if store.is_processed(email.id):
            result.emails_skipped += 1
            continue
        try:
            extracted = extractor.extract(email)
        except Exception:
            # Leave the email unprocessed so the next run retries it.
            log.exception("Extraction failed for %s (%s)", email.id, email.subject)
            continue
        for item in extracted:
            offer = Offer(**item.model_dump(), email_id=email.id, received_at=email.received_at)
            if store.upsert(offer):
                result.offers_new += 1
            else:
                result.offers_duplicate += 1
        store.mark_processed(email.id)
    return result
