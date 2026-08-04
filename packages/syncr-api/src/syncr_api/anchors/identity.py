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

**A control character is DROPPED here, and REFUSED on the user-authored path.** Both paths ask the
same question, so :func:`is_control` is the one definition of the class, and the two treatments
differ because the two sources do. A user who typed a NUL can be told to remove it, and
``schemas`` states that rejection. A publisher cannot be told anything: the byte arrives on a
calendar the user subscribes to, and refusing the event would drop real occupancy over something
the user did not do and cannot fix. Worse, ``str.split()`` and ``str.strip()`` do not remove a NUL,
so before this the byte reached a ``VARCHAR`` column and Postgres refused the whole insert. That
raise happened BEFORE the sync state was written, so anyone able to put an event on a subscribed
calendar could silently and durably stop that user's sync with one byte, leaving nothing on the
panel built to report it.

**And the trigger is not only a publisher breaking the format.** ``feeds._decoded`` falls back to
``latin-1``, which maps every byte and cannot fail, so a merely mis-encoded feed manufactures NUL
and C1 controls with no RFC violation at all. One stray byte in a Latin-1 timetable export reaches
the same column.

The digested form keeps a readable prefix, because the stored value is what a support question
is asked about. Two feeds could in principle produce one digested key by publishing UIDs that
share the prefix and collide on 32 hex characters of SHA-256; that is not a case a publisher
can reach on purpose without a preimage attack, and the alternative -- rejecting the event --
would drop real occupancy over a long identifier that is not the publisher's fault.
"""

from __future__ import annotations

import unicodedata
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


def is_control(character: str) -> bool:
    """Whether ``character`` is a control character.

    Unicode's own category rather than a hand-written range, so it covers C0, DEL and C1 with one
    test. 65 characters are ``Cc``, ten of which are also whitespace. Only NUL is fatal to a
    Postgres text column, but the rest render as nothing a person can read, and a label is for
    reading.

    ``Cc`` is not quite every class Postgres cannot store: an unpaired surrogate is ``Cs`` and
    raises at encode. It cannot arrive from a decoded feed body, because ``feeds._decoded`` uses
    strict ``utf-8-sig`` and then ``latin-1``, and neither produces a surrogate. Stated rather than
    guarded against, so a later caller feeding this JSON knows where the boundary is.

    RFC 5545 forbids a control character in a TEXT value, so a feed carrying one is already wrong.
    That is not the only way to get one: ``feeds._decoded`` falls back to ``latin-1``, which maps
    every byte, so a merely MIS-ENCODED feed manufactures NUL and C1 controls with no RFC violation
    and no hostile intent.
    """
    return unicodedata.category(character) == "Cc"


def carries_a_dropped_character(value: str | None) -> bool:
    """Whether scrubbing ``value`` would remove something.

    Asked so a reconciliation can COUNT what it altered. Dropping a byte silently changes a
    publisher's data, and a user looking at ``CompSciLecture`` on the grid, or at a match rule that
    stopped matching, needs something to go on. Whitespace controls are excluded because those are
    folded rather than dropped, which changes no word.
    """
    if value is None:
        return False
    return any(is_control(character) and not character.isspace() for character in value)


def scrubbed_text(value: str) -> str:
    """Publisher text with control characters dropped, then collapsed.

    A WHITESPACE control character is kept for the collapse to fold, so ``Two\\r\\n\\tlines`` reads
    as ``Two lines`` rather than ``Twolines``: a tab is a separator, and deleting it would join two
    words the publisher meant to keep apart. Only a control character that is not whitespace is
    dropped, which is the class Postgres refuses and the class nobody can read.

    Dropped rather than refused: see the module docstring. The caller cannot tell the publisher
    anything, and refusing the event would lose occupancy the user really has.

    **Not folded into :func:`collapsed_text`.** The user-authored path calls that one and then has
    to SEE a control character in order to reject it, so stripping inside the shared helper would
    make that rejection unreachable while its tests stayed green.
    """
    return collapsed_text(
        "".join(
            character for character in value if character.isspace() or not is_control(character)
        )
    )


def reconciliation_key(uid: str, *, limit: int = EXTERNAL_UID_MAX_LENGTH) -> str:
    """``uid`` as the stored half of the reconciliation key, fitted to the column.

    Scrubbed first, because a UID reaches the same kind of column a title does and Postgres refuses
    the insert rather than the byte. The scrub both drops control characters AND collapses
    whitespace, so two UIDs merge to one key when they differ only by a control character **or only
    by whitespace**: ``'abc'`` and ``'abc '`` are one key, and so are ``'a b'`` and ``'a\\tb'``.
    Both were two keys before the scrub existed. That is the same trade the digest makes and it is
    the right way round: a feed whose two commitments differ only in whitespace is not a real feed,
    and a merged anchor is recoverable where a sync that cannot run is not.

    The merge is length-dependent, in the safer direction. The digest is taken over the ORIGINAL
    value, so two OVERSIZED UIDs differing only by a control character keep two keys while their
    short equivalents merge. Deliberate: a duplicate anchor is cheaper than a merged one, so where
    the two readings differ the bounded path takes the more cautious one.

    Returned unchanged when it already fits, which is every real feed. Past the limit the tail
    is replaced by a digest of the WHOLE value, so two long UIDs sharing a prefix stay two
    keys.
    """
    scrubbed = scrubbed_text(uid)
    # A UID of nothing but control characters would otherwise store the empty string, and two such
    # components would then be one anchor. The digest of the original is stable and non-empty.
    if not scrubbed:
        return _digest(uid)
    if len(scrubbed) <= limit:
        return scrubbed
    kept = limit - DIGEST_LENGTH - len(DIGEST_SEPARATOR)
    return f"{scrubbed[:kept]}{DIGEST_SEPARATOR}{_digest(uid)}"


def _digest(value: str) -> str:
    """The stable short digest the bounded and the all-control cases both key on."""
    return sha256(value.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]


def series_key(series_uid: str | None) -> str | None:
    """The series half of an occurrence's identity, fitted the same way, or ``None``.

    Bounded through the same function as the occurrence UID because it is an identity too: a
    retype persists on the series, so two series collapsing onto one key would apply one
    correction to both.
    """
    return None if series_uid is None else reconciliation_key(series_uid)


def collapsed_text(value: str) -> str:
    """``value`` with every run of whitespace reduced to one space, and trimmed.

    One definition, because both a publisher's title and a user's authored name want it: a tab or
    a newline inside a label is not a label, and two spaces and one space are the same name for
    the purpose of telling two anchor types apart.
    """
    return " ".join(value.split())


def stored_title(title: str, *, limit: int = ANCHOR_TITLE_MAX_LENGTH) -> str:
    """``title`` as the row holds it: trimmed, never empty, and cut to the column.

    A cut title is the one place bounding a value changes behavior rather than only storage:
    a match rule is evaluated against the STORED title, so a substring past the limit does not
    match. That is stated rather than hidden, and no real SUMMARY is near the limit.
    """
    trimmed = scrubbed_text(title)
    return trimmed[:limit] if trimmed else UNTITLED


def stored_location(location: str | None, *, limit: int = ANCHOR_LOCATION_MAX_LENGTH) -> str | None:
    """``location`` as the row holds it, or ``None``. Nothing reads it; the column has a width."""
    if location is None:
        return None
    trimmed = scrubbed_text(location)
    return trimmed[:limit] or None
