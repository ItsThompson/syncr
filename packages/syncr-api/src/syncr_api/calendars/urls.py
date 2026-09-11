"""Accepting and normalizing a feed URL, and rejecting one syncr cannot fetch.

``webcal://`` is not a scheme any HTTP client speaks. It is a convention meaning "subscribe
to the calendar at this URL over HTTP", which every calendar client rewrites before it
fetches, and which a user pasting from a university portal will paste as-is. ``ics://`` is
the same convention under another spelling, emitted by some mobile clients. Both are accepted
and rewritten to ``https``, which is what the publisher serves.

Normalization is stored rather than applied per fetch. A stored URL is the reconciliation
key a user reads back on the Settings panel, and two rows differing only in a scheme nobody
can fetch would look like two sources for one feed.

Nothing here reaches the network. Whether the publisher answers is the fetch's answer, and
refusing to store a feed that is momentarily down would make setup depend on a publisher's
uptime. What is refused without asking is an address syncr will not fetch at all, whose
ranges are stated in ``addresses.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit, urlunsplit

from syncr_api.calendars.addresses import address_in, refusal_of
from syncr_api.calendars.config import EXTERNAL_ID_MAX_LENGTH
from syncr_api.core.errors import ValidationFailed

if TYPE_CHECKING:
    from urllib.parse import SplitResult

HTTPS: Final = "https"
HTTP: Final = "http"
WEBCAL: Final = "webcal"
ICS: Final = "ics"

# What a user may paste. `webcal` and `ics` are subscription conventions rather than schemes
# a client speaks, and both become `https`. `http` is kept rather than upgraded, because a
# university feed served over plain HTTP would otherwise fail to fetch with no explanation of
# what syncr changed.
ACCEPTED_SCHEMES: Final = (HTTPS, HTTP, WEBCAL, ICS)
REWRITTEN_SCHEMES: Final = (WEBCAL, ICS)


def normalize_feed_url(raw: str, *, trusted_hosts: frozenset[str] = frozenset()) -> str:
    """``raw`` as the URL syncr will fetch, or a stated rejection.

    The rejection names the schemes that are accepted, because "invalid URL" leaves a user
    who pasted a Google Calendar's *secret address in iCal format* with nowhere to go.
    """
    candidate = raw.strip()
    if not candidate:
        raise ValidationFailed(_rejection("it is blank"))
    if len(candidate) > EXTERNAL_ID_MAX_LENGTH:
        raise ValidationFailed(_rejection(f"it is longer than {EXTERNAL_ID_MAX_LENGTH} characters"))

    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()
    if scheme not in ACCEPTED_SCHEMES:
        stated = f"its scheme is {scheme!r}" if scheme else "it names no scheme"
        raise ValidationFailed(_rejection(stated))
    if not parts.netloc:
        raise ValidationFailed(_rejection("it names no host"))

    host = _host(parts)
    literal = address_in(host)
    if (
        literal is not None
        and parts.hostname not in trusted_hosts
        and (refusal := refusal_of(literal)) is not None
    ):
        raise ValidationFailed(refusal)

    fetchable = HTTPS if scheme in REWRITTEN_SCHEMES else scheme
    # Three things are dropped or folded, all for the reason this module exists. The fragment is
    # never sent to a server. The host is case-insensitive, so `Example.com` and `example.com` are
    # one feed and storing both would be exactly the duplication normalization prevents. And any
    # userinfo would put a credential on the Settings panel, where the address is read back.
    #
    # Path and query are preserved exactly, because a feed's token lives in one of them and
    # normalizing either would break the subscription.
    return urlunsplit((fetchable, host, parts.path, parts.query, ""))


def _host(parts: SplitResult) -> str:
    """The netloc as syncr stores it: lower-cased, with any userinfo removed.

    A port is kept as given: it is part of what identifies the endpoint, and lower-casing a number
    changes nothing.
    """
    return parts.netloc.rsplit("@", 1)[-1].lower()


def _rejection(because: str) -> str:
    return (
        f"That is not a calendar feed address syncr can read, because {because}. Paste an "
        f"ics, http, https, or webcal address. Nothing was added; every source already "
        "configured still syncs."
    )
