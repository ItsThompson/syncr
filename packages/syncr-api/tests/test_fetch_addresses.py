"""The address a fetch connects to, read on the first request and on every redirect hop.

Driven through ``httpx.MockTransport`` behind the guard, so what is under test is the real
``httpx.AsyncClient`` following a real redirect and the real ``HttpFeedFetcher`` mapping the
answer, with a recorded publisher where the socket would be. The resolver is a stub wherever a
case needs a name to answer a chosen address, and the real one wherever the case is about what a
resolver does with a spelling.

Three properties beyond the refusal itself, each asserted rather than argued.

**Nothing behind a refusal is probed.** The recorded publisher is armed with the answer a probe
would have leaked and is then asked what reached it, so a refused address produces no request at
all: no status, no timing and no transport error from inside this deployment's own network
reaches the sentence a user reads. A guard that connected first and refused afterwards is caught
twice over, by the leak in its sentence and by what the publisher saw.

**The sentence is the one the door states.** Every refused case asserts the fetch-time answer
against ``refusal_of`` for the same address *and* against what ``normalize_feed_url`` states for
the same address pasted as a literal. Two independently composed sentences are how an accept-list
and a redirect check come to disagree while both stay green.

**A check that could not run is a refusal, and a resolver states two kinds of failure.** The
fail-closed cases drive the real resolver for the two it raises as a `ValueError` rather than as a
lookup failure, because a stub can only raise what whoever wrote it thought of.

**Every range is driven, not one address.** The table below is crossed against the predicate's
own rows, so a range that gains a row without a fetch-time case has nowhere to hide.
"""

from __future__ import annotations

from ipaddress import ip_address
from socket import EAI_NONAME, gaierror
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

import httpx
import pytest

from syncr_api.calendars.addresses import REFUSED_RANGES, address_in, refusal_of
from syncr_api.calendars.config import FETCH_TIMEOUT_SECONDS
from syncr_api.calendars.feeds import (
    FeedBody,
    FeedUnreachable,
    HttpFeedFetcher,
    create_feed_client,
)
from syncr_api.calendars.fetch_addresses import (
    RefusingTransport,
    refusal_for_host,
    resolved_addresses,
)
from syncr_api.calendars.urls import normalize_feed_url
from syncr_api.core.errors import ValidationFailed
from syncr_api.core.settings import EnvSettings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.calendars.fetch_addresses import AddressResolution

FEED_URL = "https://example.ac.uk/timetable.ics"
MIRROR_URL = "https://mirror.example.ac.uk/timetable.ics"
FEED_BODY = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"

PUBLISHER_ADDRESS: Final = "93.184.216.34"
# The host metadata service: the address this whole seam exists for, because a request syncr
# issues to it carries syncr's own credentials.
METADATA_ADDRESS: Final = "169.254.169.254"

# The decimal and hexadecimal spellings of the loopback address. `ipaddress` reads neither, so
# both pass the door as names; a resolver reads both as the address they spell.
DECIMAL_LOOPBACK: Final = "2130706433"
HEXADECIMAL_LOOPBACK: Final = "0x7f000001"

# An international name, and the ASCII form httpx encodes it to before the connection resolves
# it. The stub resolver below is keyed by the encoded form, so reading the name in the other
# spelling finds nothing to answer with.
UNICODE_NAME: Final = "bücher.example"
ENCODED_NAME: Final = "xn--bcher-kva.example"

# Two names the door stores and the resolver will not encode: a label with nothing in it, and one
# over the 63 bytes DNS allows. Neither is crafted; the first is one typed dot too many.
EMPTY_LABEL_URL: Final = "https://a..b.example/t.ics"
OVER_LONG_LABEL_URL: Final = f"https://{'a' * 64}.example/t.ics"

# A port nothing serves, so a client with no guard in front of it fails to connect rather than
# reaching something. Only the unguarded case ever opens a socket at all.
CLOSED_PORT: Final = 1

# One address the resolver could answer inside each range, with the range the refusal must name.
# Both families, and the IPv4-mapped spelling of the ranges a mapped address can carry, because
# a resolver asked for a name with an A record can answer in the mapped form.
REFUSED_RESOLUTIONS: Final = (
    ("0.0.0.0", "the unspecified address"),
    ("::", "the unspecified address"),
    ("127.0.0.1", "a loopback address"),
    ("::1", "a loopback address"),
    ("::ffff:127.0.0.1", "a loopback address"),
    (METADATA_ADDRESS, "a link-local address"),
    ("fe80::1", "a link-local address"),
    (f"::ffff:{METADATA_ADDRESS}", "a link-local address"),
    ("fd00::1", "a unique-local address"),
    ("fec0::1", "a site-local address"),
    ("224.0.0.1", "a multicast address"),
    ("ff02::1", "a multicast address"),
    ("10.0.0.1", "a private-range address"),
    ("172.16.0.1", "a private-range address"),
    ("192.168.1.1", "a private-range address"),
    ("::ffff:192.168.1.1", "a private-range address"),
)

# The other direction: a publisher answers on a public address in either family, and the mapped
# spelling of one. A guard that refused these would be found by nobody until a real feed was
# added.
FETCHED_RESOLUTIONS: Final = (
    PUBLISHER_ADDRESS,
    "2606:2800:220:1:248:1893:25c8:1946",
    f"::ffff:{PUBLISHER_ADDRESS}",
)


def probe_answer() -> httpx.Response:
    """What a probe of an address inside this deployment's own network would have leaked.

    Armed rather than omitted: a guard that connected first and refused afterwards then reddens on
    the status in its own sentence, which is the disclosure, as well as on having been seen.
    """
    return httpx.Response(500)


def recorded(
    *answers: httpx.Response,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """A publisher answering ``answers`` in order, and the list of what reached it.

    A request the test recorded no answer for raises rather than being served a default, because
    a guard that let one extra request through would otherwise be indistinguishable from a guard
    that let none through.
    """
    seen: list[httpx.Request] = []
    remaining = list(answers)

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return remaining.pop(0)

    return httpx.MockTransport(handle), seen


def answering(*spellings: str) -> AddressResolution:
    """A resolver answering the same addresses for whatever name it is asked."""

    async def resolve(_host: str) -> Sequence[str]:
        return spellings

    return resolve


def answering_by_name(names: dict[str, tuple[str, ...]]) -> AddressResolution:
    """A resolver answering per name, and raising for a name the case did not declare."""

    async def resolve(host: str) -> Sequence[str]:
        return names[host]

    return resolve


def fetcher_over(
    publisher: httpx.MockTransport, *, resolve: AddressResolution
) -> tuple[HttpFeedFetcher, httpx.AsyncClient]:
    """The real fetcher over the real client, with the guard in front of a recorded publisher."""
    client = httpx.AsyncClient(
        transport=RefusingTransport(publisher, resolve=resolve),
        timeout=FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
    )
    return HttpFeedFetcher(client), client


def door_refusal(spelling: str) -> str:
    """What the normalizer states for the same address pasted as a literal."""
    hosted = f"[{spelling}]" if ":" in spelling else spelling
    with pytest.raises(ValidationFailed) as raised:
        normalize_feed_url(f"https://{hosted}/t.ics")
    return raised.value.detail


def urls_of(requests: list[httpx.Request]) -> list[str]:
    return [str(request.url) for request in requests]


# --------------------------------------------------------------------------------
# A name that resolves into a refused range is not fetched
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spelling", "range_name"),
    REFUSED_RESOLUTIONS,
    ids=[spelling for spelling, _ in REFUSED_RESOLUTIONS],
)
async def test_a_name_resolving_into_a_refused_range_is_unreachable(
    spelling: str, range_name: str
) -> None:
    publisher, seen = recorded(probe_answer())
    reader, client = fetcher_over(publisher, resolve=answering(spelling))

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedUnreachable)
    # The range by name, so deleting one row reddens that row's cases rather than every case.
    assert range_name in answer.reason
    # The predicate's own sentence, and the same sentence the door states for the literal.
    assert answer.reason == refusal_of(ip_address(spelling))
    assert answer.reason == door_refusal(spelling)
    # Nothing was sent, so nothing about what is at that address is in the answer.
    assert seen == []


def test_every_stated_range_is_driven_at_fetch_time() -> None:
    # Computed from the predicate's rows rather than restated, so a range added to the module
    # with no fetch-time case here goes red.
    assert {range_name for _, range_name in REFUSED_RESOLUTIONS} == {
        range_name for range_name, _ in REFUSED_RANGES
    }


@pytest.mark.parametrize("spelling", FETCHED_RESOLUTIONS)
async def test_a_publishers_address_is_fetched(spelling: str) -> None:
    publisher, seen = recorded(httpx.Response(200, content=FEED_BODY))
    reader, client = fetcher_over(publisher, resolve=answering(spelling))

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedBody)
    assert answer.body.startswith("BEGIN:VCALENDAR")
    assert urls_of(seen) == [FEED_URL]


# --------------------------------------------------------------------------------
# Every address the resolver answers, not the first
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spellings",
    [
        (PUBLISHER_ADDRESS, METADATA_ADDRESS),
        (METADATA_ADDRESS, PUBLISHER_ADDRESS),
        (PUBLISHER_ADDRESS, PUBLISHER_ADDRESS, METADATA_ADDRESS),
    ],
    ids=["refused second", "refused first", "refused last of three"],
)
async def test_one_refused_record_refuses_the_name_wherever_it_sits(
    spellings: tuple[str, ...],
) -> None:
    # A name with several records is answered in an order the client does not choose, so a check
    # that read the first record would refuse or fetch the same name depending on the resolver.
    publisher, seen = recorded(probe_answer())
    reader, client = fetcher_over(publisher, resolve=answering(*spellings))

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedUnreachable)
    assert answer.reason == refusal_of(ip_address(METADATA_ADDRESS))
    assert seen == []


async def test_a_name_whose_every_record_is_public_is_fetched() -> None:
    # The control for the three cases above: without it they would pass just as happily against
    # a guard that refused every name answering more than one address.
    publisher, seen = recorded(httpx.Response(200, content=FEED_BODY))
    reader, client = fetcher_over(
        publisher, resolve=answering(PUBLISHER_ADDRESS, "2606:2800:220:1:248:1893:25c8:1946")
    )

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedBody)
    assert urls_of(seen) == [FEED_URL]


# --------------------------------------------------------------------------------
# Every hop, not the first request
# --------------------------------------------------------------------------------


async def test_a_redirect_into_a_refused_range_is_refused_at_the_hop() -> None:
    publisher, seen = recorded(
        httpx.Response(302, headers={"Location": f"http://{METADATA_ADDRESS}/"}), probe_answer()
    )
    reader, client = fetcher_over(
        publisher,
        resolve=answering_by_name(
            {"example.ac.uk": (PUBLISHER_ADDRESS,), METADATA_ADDRESS: (METADATA_ADDRESS,)}
        ),
    )

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedUnreachable)
    assert answer.reason == refusal_of(ip_address(METADATA_ADDRESS))
    # The hop was never issued: the recorded publisher saw the first request and nothing after it.
    assert urls_of(seen) == [FEED_URL]


async def test_a_second_hop_is_read_as_well_as_the_first() -> None:
    # A guard that checked the first request and the first hop would still follow a chain into a
    # refused range, and a portal that answers one redirect can answer two.
    publisher, seen = recorded(
        httpx.Response(302, headers={"Location": MIRROR_URL}),
        httpx.Response(302, headers={"Location": "http://10.0.0.1/timetable.ics"}),
        probe_answer(),
    )
    reader, client = fetcher_over(
        publisher,
        resolve=answering_by_name(
            {
                "example.ac.uk": (PUBLISHER_ADDRESS,),
                "mirror.example.ac.uk": (PUBLISHER_ADDRESS,),
                "10.0.0.1": ("10.0.0.1",),
            }
        ),
    )

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedUnreachable)
    assert answer.reason == refusal_of(ip_address("10.0.0.1"))
    assert urls_of(seen) == [FEED_URL, MIRROR_URL]


async def test_a_redirect_to_a_publisher_is_still_followed() -> None:
    # The control for the two cases above. A guard that refused every hop would report a
    # university portal's own redirect as an unreachable feed, which is the behavior the client
    # follows redirects to avoid.
    publisher, seen = recorded(
        httpx.Response(302, headers={"Location": MIRROR_URL}),
        httpx.Response(200, content=FEED_BODY),
    )
    reader, client = fetcher_over(
        publisher,
        resolve=answering_by_name(
            {"example.ac.uk": (PUBLISHER_ADDRESS,), "mirror.example.ac.uk": (PUBLISHER_ADDRESS,)}
        ),
    )

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedBody)
    assert urls_of(seen) == [FEED_URL, MIRROR_URL]


async def test_an_international_name_is_read_in_the_form_the_connection_resolves() -> None:
    # httpx encodes an international name to ASCII once and hands the encoded form down, so a
    # check reading the name in its unicode spelling would ask the resolver a question the
    # connection never asks.
    publisher, seen = recorded(probe_answer())
    reader, client = fetcher_over(
        publisher, resolve=answering_by_name({ENCODED_NAME: ("10.0.0.1",)})
    )

    async with client:
        answer = await reader.get(f"https://{UNICODE_NAME}/t.ics", cursor=None)

    assert isinstance(answer, FeedUnreachable)
    assert answer.reason == refusal_of(ip_address("10.0.0.1"))
    assert seen == []


# --------------------------------------------------------------------------------
# A check that could not run is a refusal
# --------------------------------------------------------------------------------


async def failing_resolution(_host: str) -> Sequence[str]:
    raise gaierror(EAI_NONAME, "nodename nor servname provided, or not known")


@pytest.mark.parametrize(
    ("url", "resolve"),
    [
        (FEED_URL, failing_resolution),
        (FEED_URL, answering()),
        (FEED_URL, answering("not-an-address")),
        (EMPTY_LABEL_URL, resolved_addresses),
        (OVER_LONG_LABEL_URL, resolved_addresses),
    ],
    ids=[
        "the resolver failed",
        "the resolver answered nothing",
        "an answer it cannot read",
        "a real resolver refusing an empty label",
        "a real resolver refusing a label over 63 bytes",
    ],
)
async def test_an_address_that_could_not_be_read_is_not_connected_to(
    url: str, resolve: AddressResolution
) -> None:
    # The last two run the real resolver, because the property is which failures a resolver states
    # rather than which ones a stub was written to raise: a lookup failure is an OSError and a name
    # it will not encode is a ValueError, so a guard reading one of the two lets the other past
    # itself and past the closed union of answers the fetch path promises.
    #
    # Every address in the table is one the door stores, so each is reachable from a stored row
    # rather than from a crafted request.
    assert normalize_feed_url(url) == url

    publisher, seen = recorded(probe_answer())
    reader, client = fetcher_over(publisher, resolve=resolve)

    async with client:
        answer = await reader.get(url, cursor=None)

    named = urlsplit(url).hostname
    assert isinstance(answer, FeedUnreachable)
    assert named is not None
    assert named in answer.reason
    assert "does not connect to an address it has not checked" in answer.reason
    assert "Every source already configured still syncs" in answer.reason
    assert seen == []


# --------------------------------------------------------------------------------
# The real resolver, on the spellings the door cannot read
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("spelling", [DECIMAL_LOOPBACK, HEXADECIMAL_LOOPBACK])
async def test_a_spelling_the_door_stores_is_refused_by_the_resolver(spelling: str) -> None:
    # The door reads dotted and colon spellings only, so both of these are stored as names. The
    # resolver reads them as the loopback address they spell, which is what closes them here.
    #
    # Both rest on the platform resolver accepting them through `inet_aton`, which glibc and BSD do
    # and musl does not, so this case states what the deployment's own C library reads rather than a
    # property of the language. On a musl image it fails here rather than silently widening what
    # syncr fetches, because a spelling the resolver rejects is refused rather than fetched.
    assert address_in(spelling) is None
    assert normalize_feed_url(f"http://{spelling}/t.ics") == f"http://{spelling}/t.ics"

    assert "127.0.0.1" in await resolved_addresses(spelling)
    assert await refusal_for_host(spelling) == refusal_of(ip_address("127.0.0.1"))


async def test_a_name_the_door_cannot_read_at_all_is_refused_on_every_record() -> None:
    # `localhost` is a name, so the door stores it. It answers two addresses on this platform and
    # the guard reads all of them, so it is refused whichever the socket would have taken.
    answered = await resolved_addresses("localhost")

    assert answered
    assert all(refusal_of(ip_address(spelling)) is not None for spelling in answered)
    refusal = await refusal_for_host("localhost")
    assert refusal is not None
    assert "a loopback address" in refusal


async def test_the_client_the_app_wires_reads_the_address_before_it_connects() -> None:
    # The composition, driven rather than inspected. Without the guard the client would open a
    # socket to a closed port and answer the connection's own error instead of the refusal.
    async with create_feed_client() as client:
        answer = await HttpFeedFetcher(client).get(
            f"http://127.0.0.1:{CLOSED_PORT}/t.ics", cursor=None
        )

    assert answer == FeedUnreachable(str(refusal_of(ip_address("127.0.0.1"))))


async def test_closing_the_client_closes_the_transport_the_guard_wraps() -> None:
    # The guard sits between the client and the connection pool, so a guard that swallowed the
    # close would hold every pooled connection a worker tick opened for the life of the process.
    class Closing(httpx.AsyncBaseTransport):
        closed = False

        async def aclose(self) -> None:
            self.closed = True

    pool = Closing()

    async with httpx.AsyncClient(transport=RefusingTransport(pool)):
        assert not pool.closed

    assert pool.closed


# --------------------------------------------------------------------------------
# This deployment's own hosts earn no exemption
# --------------------------------------------------------------------------------


async def test_this_deployments_own_postgres_and_api_hosts_are_refused() -> None:
    """The two hosts the deployment configures for itself, read through the same predicate.

    Derived from the settings module rather than restated, and asserted on the range each falls
    in rather than on refusal alone: an unresolvable name is refused too, so a refusal that named
    no range would credit the guard for a resolution that simply failed.
    """
    postgres = urlsplit(str(EnvSettings.model_fields["database_url"].default)).hostname
    api_host = str(EnvSettings.model_fields["host"].default)

    assert postgres is not None
    postgres_refusal = await refusal_for_host(postgres)
    api_refusal = await refusal_for_host(api_host)

    assert postgres_refusal is not None
    assert "a loopback address" in postgres_refusal
    assert api_refusal is not None
    assert "the unspecified address" in api_refusal
