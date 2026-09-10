"""The addresses syncr refuses to fetch, driven through the one site that normalizes a feed.

Two directions, and each is what makes the other meaningful.

**A literal inside a refused range does not become a stored feed.** Every range the predicate
states is driven through the normalizer, in each spelling a host field admits: bare, bracketed,
with a port, with userinfo, and as an IPv4 address carried inside an IPv6 one. The refusal names
the range, so deleting one row reddens that row's cases rather than all of them at once.

**A publisher's address still normalizes, and still reaches the write.** A refusal that also
refused ``example.com`` or a public literal would be found by nobody until a user pasted a real
feed, so the same path is driven the other way, through the service that admits a source.

The rule that the ranges are stated in one module, and the derivation of where an address is
normalized, are in ``test_refused_address_boundary.py``: those are claims about the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from syncr_api.calendars.addresses import REFUSED_RANGES, address_in, refusal_of
from syncr_api.calendars.config import ANCHOR_SOURCE, ICS
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.calendars.service import CalendarSourceService, NewSource
from syncr_api.calendars.urls import normalize_feed_url
from syncr_api.core.errors import ValidationFailed
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES

if TYPE_CHECKING:
    from syncr_api.calendars.config import CalendarProvider

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
OWNER = Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=ALL_SCOPES)

A_PRIVATE_FEED = "http://10.0.0.1/t.ics"
A_PUBLISHED_FEED = "https://example.com/t.ics"

# The decimal and hexadecimal spellings of 127.0.0.1: an address to a resolver, and no address
# at all to the library that states the ranges.
DECIMAL_LOOPBACK: Final = "2130706433"
HEXADECIMAL_LOOPBACK: Final = "0x7f000001"

# A feed address inside each range, in each spelling a host field admits, with the range the
# refusal must name. The completeness check below crosses the names here against the predicate's
# own rows, so a range added to the module without a case here goes red.
REFUSED_FEEDS: Final = (
    ("https://127.0.0.1/t.ics", "a loopback address"),
    ("https://127.0.0.1:8443/t.ics", "a loopback address"),
    ("https://[::1]/t.ics", "a loopback address"),
    ("https://::1/t.ics", "a loopback address"),
    ("https://[::ffff:127.0.0.1]/t.ics", "a loopback address"),
    ("https://user:secret@127.0.0.1/t.ics", "a loopback address"),  # pragma: allowlist secret
    ("webcal://169.254.169.254/t.ics", "a link-local address"),
    ("https://[fe80::1]:8443/t.ics", "a link-local address"),
    ("https://[::ffff:169.254.169.254]/t.ics", "a link-local address"),
    ("https://[fd00::1]/t.ics", "a unique-local address"),
    ("https://[fec0::1]/t.ics", "a site-local address"),
    (A_PRIVATE_FEED, "a private-range address"),
    ("https://172.16.0.1/t.ics", "a private-range address"),
    ("ics://192.168.1.1/t.ics", "a private-range address"),
    ("https://[::ffff:192.168.1.1]/t.ics", "a private-range address"),
    ("https://0.0.0.0/t.ics", "the unspecified address"),
    ("https://[::]/t.ics", "the unspecified address"),
    ("https://224.0.0.1/t.ics", "a multicast address"),
    ("https://[ff02::1]/t.ics", "a multicast address"),
)

# The other direction. A publisher serves a feed on a name or on a public address, in either
# family, with or without a port, and every one of these must survive the refusal above.
FETCHABLE_FEEDS: Final = (
    A_PUBLISHED_FEED,
    "https://example.ac.uk/timetable.ics",
    "webcal://example.com/t.ics",
    "https://example.com:8443/t.ics",
    "https://93.184.216.34/t.ics",
    "https://93.184.216.34:8443/t.ics",
    "https://[2606:2800:220:1:248:1893:25c8:1946]/t.ics",
    "https://[::ffff:93.184.216.34]/t.ics",
)


def refusal_of_host(url: str) -> str | None:
    """The refusal this URL's host would earn, or ``None``: the reading a caller does."""
    literal = address_in(urlsplit(url).netloc)
    return None if literal is None else refusal_of(literal)


# --------------------------------------------------------------------------------
# A literal inside a refused range does not become a stored feed
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "range_name"), REFUSED_FEEDS, ids=[raw for raw, _ in REFUSED_FEEDS]
)
def test_an_address_inside_a_refused_range_is_not_normalized(raw: str, range_name: str) -> None:
    with pytest.raises(ValidationFailed) as raised:
        normalize_feed_url(raw)

    detail = raised.value.detail
    # The range by name, so a deleted row reddens the cases of that row rather than every case.
    assert range_name in detail
    # What syncr will fetch instead, which is the half of the sentence a user can act on.
    assert "on the public internet" in detail
    assert "Paste the address your calendar provider publishes" in detail
    assert "Every source already configured still syncs" in detail


def test_every_stated_range_is_driven_through_the_normalizer() -> None:
    # The completeness check for the table above. Computed from the predicate's own rows rather
    # than restated, so a range added to the module with no case here has nowhere to hide.
    assert {range_name for _, range_name in REFUSED_FEEDS} == {
        range_name for range_name, _ in REFUSED_RANGES
    }


@pytest.mark.parametrize("raw", FETCHABLE_FEEDS)
def test_a_publishers_address_still_normalizes(raw: str) -> None:
    normalized = normalize_feed_url(raw)

    assert normalized.endswith(".ics")
    assert refusal_of_host(normalized) is None


def test_a_spelling_ipaddress_cannot_read_is_not_a_literal() -> None:
    # `ipaddress` reads the dotted and colon spellings only, so the decimal and hexadecimal forms
    # of an address are names here rather than literals, and a resolver still accepts them. A host
    # name is the same class: `localhost` resolves to two refused addresses and is neither. What
    # refuses all three is the same question asked of the address a socket connects to.
    assert address_in(DECIMAL_LOOPBACK) is None
    assert address_in(HEXADECIMAL_LOOPBACK) is None
    assert address_in("localhost") is None
    assert (
        normalize_feed_url(f"https://{DECIMAL_LOOPBACK}/t.ics")
        == f"https://{DECIMAL_LOOPBACK}/t.ics"
    )


def test_the_interpreter_reads_a_mapped_address_as_the_address_it_carries() -> None:
    # `ipaddress` classified an IPv4-mapped IPv6 address by its own 128-bit value until CPython
    # gh-113171, released in 3.12.4, which reads the mapped IPv4 address instead. The mapped rows
    # of the table above rely on that, so an interpreter below the floor fails here rather than
    # silently widening what syncr fetches.
    assert ip_address("::ffff:127.0.0.1").is_loopback
    assert ip_address("::ffff:169.254.169.254").is_link_local
    assert ip_address("::ffff:192.168.1.1").is_private
    assert ip_address("::ffff:0.0.0.0").is_unspecified


# --------------------------------------------------------------------------------
# Nothing is stored, and the one admission path is where the refusal happens
# --------------------------------------------------------------------------------


@dataclass
class RecordingSources:
    """The repository surface ``add_source`` reaches, recording rather than persisting.

    Two methods, because those are the two the add path calls. Anything else this double is
    asked for is a change in what the path does, and an :class:`AttributeError` says so.
    """

    created: list[str] = field(default_factory=list)
    asked: list[str] = field(default_factory=list)

    async def find_by_external_id(
        self, provider: CalendarProvider, external_id: str
    ) -> CalendarSourceRecord | None:
        self.asked.append(external_id)
        return None

    async def create(self, *, external_id: str, **rest: object) -> CalendarSourceRecord:
        self.created.append(external_id)
        return CalendarSourceRecord(
            id=uuid4(),
            tenant_id=OWNER.tenant_id,
            provider=ICS,
            role=ANCHOR_SOURCE,
            display_name="Feed",
            external_id=external_id,
            included=True,
            horizon_days=None,
            created_at=NOW,
            sync_state=SyncStateRecord(),
        )


def service_over(sources: RecordingSources) -> CalendarSourceService:
    """The service with only the collaborator the add path uses.

    The other four are absent rather than faked: ``add_source`` reaches none of them, and a
    ``None`` that is reached raises where a permissive fake would pass silently.
    """
    return CalendarSourceService(
        sources=sources,  # type: ignore[arg-type]  # a double over the repository's surface
        syncer=None,  # type: ignore[arg-type]
        versions=None,  # type: ignore[arg-type]
        solve_requests=None,  # type: ignore[arg-type]
        clock=lambda: NOW,
        remote_calendars=None,  # type: ignore[arg-type]
        feeds=None,  # type: ignore[arg-type]
    )


async def test_a_refused_address_is_refused_before_anything_is_written() -> None:
    sources = RecordingSources()

    with pytest.raises(ValidationFailed):
        await service_over(sources).add_source(
            OWNER, NewSource(provider=ICS, display_name="Feed", external_id=A_PRIVATE_FEED)
        )

    assert sources.created == []
    # Refused before the duplicate lookup too, so a refused address never becomes a query either.
    assert sources.asked == []


async def test_a_publishers_address_reaches_the_write_through_the_same_path() -> None:
    # The other direction on the same path. Without it, a refusal that refused everything would
    # leave the assertions above true with no source addable at all.
    sources = RecordingSources()

    await service_over(sources).add_source(
        OWNER, NewSource(provider=ICS, display_name="Feed", external_id=A_PUBLISHED_FEED)
    )

    assert sources.created == [A_PUBLISHED_FEED]
