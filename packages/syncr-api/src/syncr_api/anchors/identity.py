"""Turning a publisher's values into ones a column can hold, without merging two commitments.

Every value a feed contributes to an anchor row is one the publisher chose the length of, and
nothing upstream bounds any of them: the feed body is capped at 8 MiB and one property may be
all of it. So each is bounded here, at the one place an event becomes a row, rather than at a
``VARCHAR`` that raises on flush and turns one oversized SUMMARY into a whole feed's sync
failing.

**A label is cut and an identity is digested, and the difference matters.** Cutting a title
loses characters nobody reads. Cutting a UID would map two distinct commitments onto one
reconciliation key, so two lectures would become one anchor that alternates between them on
every sync, each one displacing whatever the other had displaced. A digest keeps distinct
inputs distinct while fitting the column, and it is stable across runs, which is what
reconciliation needs: the same UID has to produce the same key next week.

The digested form keeps a readable prefix, because the stored value is what a support question
is asked about. Two feeds could in principle produce one digested key by publishing UIDs that
share the prefix and collide on 32 hex characters of SHA-256; that is not a case a publisher
can reach on purpose without a preimage attack, and the alternative -- rejecting the event --
would drop real occupancy over a long identifier that is not the publisher's fault.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Final

from syncr_api.anchors.config import (
    ANCHOR_LOCATION_MAX_LENGTH,
    ANCHOR_TITLE_MAX_LENGTH,
    EXTERNAL_UID_MAX_LENGTH,
)

# How much of the digest is kept, and what separates it from the prefix. 32 hex characters is
# 128 bits. The separator is a character an ICS UID may legally contain, so the digested form
# is not claimed to be unforgeable: what it has to be is deterministic and injective in
# practice, which does not need a reserved character.
DIGEST_LENGTH: Final = 32
DIGEST_SEPARATOR: Final = "~"

# A title with nothing in it after trimming. A feed may publish a component with no SUMMARY at
# all, and a nameless row on the grid reads as a rendering fault rather than as a commitment
# whose publisher named nothing.
UNTITLED: Final = "Untitled commitment"


def reconciliation_key(uid: str, *, limit: int = EXTERNAL_UID_MAX_LENGTH) -> str:
    """``uid`` as the stored half of the reconciliation key, fitted to the column.

    Returned unchanged when it already fits, which is every real feed. Past the limit the tail
    is replaced by a digest of the WHOLE value, so two long UIDs sharing a prefix stay two
    keys.
    """
    if len(uid) <= limit:
        return uid
    kept = limit - DIGEST_LENGTH - len(DIGEST_SEPARATOR)
    digest = sha256(uid.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]
    return f"{uid[:kept]}{DIGEST_SEPARATOR}{digest}"


def series_key(series_uid: str | None) -> str | None:
    """The series half of an occurrence's identity, fitted the same way, or ``None``.

    Bounded through the same function as the occurrence UID because it is an identity too: a
    retype persists on the series, so two series collapsing onto one key would apply one
    correction to both.
    """
    return None if series_uid is None else reconciliation_key(series_uid)


def stored_title(title: str, *, limit: int = ANCHOR_TITLE_MAX_LENGTH) -> str:
    """``title`` as the row holds it: trimmed, never empty, and cut to the column.

    A cut title is the one place bounding a value changes behavior rather than only storage:
    a match rule is evaluated against the STORED title, so a substring past the limit does not
    match. That is stated rather than hidden, and no real SUMMARY is near the limit.
    """
    trimmed = " ".join(title.split())
    return trimmed[:limit] if trimmed else UNTITLED


def stored_location(location: str | None, *, limit: int = ANCHOR_LOCATION_MAX_LENGTH) -> str | None:
    """``location`` as the row holds it, or ``None``. Nothing reads it; the column has a width."""
    if location is None:
        return None
    trimmed = " ".join(location.split())
    return trimmed[:limit] or None
