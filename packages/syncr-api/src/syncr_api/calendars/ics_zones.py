"""Mapping a feed's ``TZID`` onto an IANA zone, or rejecting the event by name.

A ``TZID`` is a free string. RFC 5545 does not require it to be an IANA key, and real
publishers emit Windows zone names (Exchange), the deprecated CDO integers (older
Outlook), and a handful of legacy tz aliases. syncr resolves wall time through the tz
database, so a zone it cannot resolve is not a zone at all.

Two answers only, and this is the whole reason the module exists: an alias the table knows
maps to an IANA key, and anything else **rejects the event with the zone named**. Guessing
a nearby zone would place a lecture an hour out and report success, which is the failure
this product has no way to detect afterwards.

The table is deliberately small and covers the zones a UK-based user's feeds actually
carry. It grows by a reviewed line when a real feed needs one, which is what "a known-alias
table" means: a set someone signed off, not a heuristic.

A ``TZID`` that is ALREADY an IANA key needs no entry, because :func:`resolve_zone` in the
domain answers it. The table is consulted only after that fails.
"""

from __future__ import annotations

from typing import Final

from syncr_domain.zones import UnknownZoneError, resolve_zone

# Windows and CDO zone names onto IANA keys. Keys are compared upper-cased and with
# surrounding whitespace stripped, so "GMT Standard Time" and "gmt standard time" are one
# entry.
#
# The Windows names come from the CLDR windowsZones mapping, territory 001 (the default
# territory for each Windows zone). Only the entries a real feed in this deployment's
# catchment has produced are listed: a full 140-row transcription would be unreviewable and
# most of it unreachable.
#
# **No entry here may be a key `zoneinfo` already resolves.** The table is consulted only
# after direct resolution fails, so such an entry would be dead. That includes every legacy
# tz alias a publisher might emit (`GB`, `Eire`, `GMT`, `Europe/Belfast`): the tz database
# carries them as links and answers them itself. A test asserts the property rather than
# leaving it to a reader to re-derive.
TZID_ALIASES: Final[dict[str, str]] = {
    # Windows, as Exchange and Outlook emit them.
    "GMT STANDARD TIME": "Europe/London",
    "GREENWICH STANDARD TIME": "Atlantic/Reykjavik",
    "W. EUROPE STANDARD TIME": "Europe/Berlin",
    "CENTRAL EUROPE STANDARD TIME": "Europe/Budapest",
    "CENTRAL EUROPEAN STANDARD TIME": "Europe/Warsaw",
    "ROMANCE STANDARD TIME": "Europe/Paris",
    "E. EUROPE STANDARD TIME": "Europe/Chisinau",
    "FLE STANDARD TIME": "Europe/Kyiv",
    "GTB STANDARD TIME": "Europe/Bucharest",
    "EASTERN STANDARD TIME": "America/New_York",
    "CENTRAL STANDARD TIME": "America/Chicago",
    "MOUNTAIN STANDARD TIME": "America/Denver",
    "PACIFIC STANDARD TIME": "America/Los_Angeles",
    # The display strings older Outlook emits as a TZID, and the bare `Z` a few feeds use
    # where the standard puts a suffix on the value instead.
    "(GMT) GREENWICH MEAN TIME : DUBLIN, EDINBURGH, LISBON, LONDON": "Europe/London",
    "(UTC) COORDINATED UNIVERSAL TIME": "UTC",
    "COORDINATED UNIVERSAL TIME": "UTC",
    "Z": "UTC",
}


class UnmappedZoneError(UnknownZoneError):
    """A ``TZID`` naming neither an IANA zone nor a known alias.

    Extends the domain's own rejection so a caller that already handles an unknown zone
    handles this too, and carries the offending name so the panel can state it.
    """

    def __init__(self, tzid: str) -> None:
        self.tzid = tzid
        super().__init__(
            f"{tzid!r} names no IANA time zone and no known alias, so syncr cannot tell "
            "when this event happens"
        )


def resolve_tzid(tzid: str) -> str:
    """The IANA key ``tzid`` names, directly or through the alias table.

    Raises :class:`UnmappedZoneError` naming the zone otherwise. Nothing here falls back to
    a default: an event placed in the wrong zone is occupancy in the wrong hour, and the
    plan built on it would look entirely reasonable.
    """
    candidate = tzid.strip()
    try:
        resolve_zone(candidate)
    except UnknownZoneError:
        aliased = TZID_ALIASES.get(candidate.upper())
        if aliased is None:
            raise UnmappedZoneError(tzid) from None
        return aliased
    return candidate
