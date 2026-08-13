"""The address a fetch will connect to, read against the ranges syncr will not fetch.

A stored feed address is a name far more often than an address, and a name is not an address: it
is a question a resolver answers at the moment of the fetch. So the answer the normalizer got
when the address was pasted cannot stand in for the answer the socket gets, and three things
reach a refused range without ever passing the normalizer:

- a name that resolves inward, whether because this deployment's own resolver says so or because
  whoever controls the name says so;
- a publisher that answers a redirect, whose target nobody pasted;
- a spelling the address library cannot read, like the decimal form of a dotted quad, which is no
  literal at the door and is an address to a resolver.

Every request the feed client makes is read here, hop by hop, and the ranges are still stated
once: this module asks ``calendars.addresses`` and states no range of its own.

**Every address the resolver answers is read, not the first.** A name carrying one public record
and one inward record would otherwise be fetched or refused depending on which record the socket
happened to pick.

**Nothing behind a refusal is probed.** The answer is composed before the request is sent, so no
status, no timing and no transport error from an address inside this deployment's own network
reaches the sentence a user reads.

**A check that could not run is a refusal.** A request allowed through because its resolution
failed is an unchecked request, which is the state this module exists to prevent. A resolver refuses
an address in two ways and both are read: a lookup that answers nothing, and a name it will not
encode, which is not an ``OSError``.

**One limit, stated because it bounds what this module promises.** The resolution here and the
resolution the socket makes are two separate calls, so a name that answers a public address to
the first and an inward address to the second is refused by neither. Closing that means pinning
the connection to the address that was read, which is a property of the socket rather than of
the request.
"""

from __future__ import annotations

import asyncio
import socket
from typing import TYPE_CHECKING

import httpx

from syncr_api.calendars.addresses import address_in, refusal_of

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

type AddressResolution = Callable[[str], Awaitable[Sequence[str]]]


class RefusedAddress(httpx.TransportError):
    """The request was never sent, because the address it would connect to is refused.

    A transport error rather than a response, because nothing answered: a fabricated status
    would put a sentence about syncr's own perimeter where a publisher's answer goes.
    """

    def __init__(self, refusal: str) -> None:
        super().__init__(refusal)
        self.refusal = refusal


async def resolved_addresses(host: str) -> Sequence[str]:
    """Every address the resolver answers for ``host``, in the spelling it answers with.

    The event loop's own resolver, which is the resolution the connection would make.
    """
    answers = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    # The address is the first member of the socket address for every internet family. The one
    # non-internet form the annotation admits spells it as bytes, and a spelling the reader below
    # cannot read is refused rather than skipped.
    return tuple(str(answer[4][0]) for answer in answers)


async def refusal_for_host(
    host: str, *, resolve: AddressResolution = resolved_addresses
) -> str | None:
    """Why syncr will not connect to ``host``, or ``None`` when it will.

    Every address the resolver answers is read, so one refused record refuses the name whichever
    record a socket would have chosen.
    """
    try:
        spellings = await resolve(host)
    except (OSError, UnicodeError):
        # The resolver states a name it will not encode as a ``UnicodeError``, which is a
        # ``ValueError`` rather than a lookup failure: an empty label or one over 63 bytes. Reading
        # only the lookup failure lets it past both this refusal and the closed union of answers
        # the fetch path promises its caller.
        return _unread(host)
    if not spellings:
        return _unread(host)
    for spelling in spellings:
        address = address_in(spelling)
        if address is None:
            return _unread(host)
        refusal = refusal_of(address)
        if refusal is not None:
            return refusal
    return None


class RefusingTransport(httpx.AsyncBaseTransport):
    """Another transport, with the address of every request read before it is sent.

    Wrapping the transport rather than reading one URL is what makes the check hold over a
    redirect: a client following a hop asks its transport again, so every hop is read on the same
    rows as the address a user pasted.
    """

    def __init__(
        self, inner: httpx.AsyncBaseTransport, *, resolve: AddressResolution = resolved_addresses
    ) -> None:
        self._inner = inner
        self._resolve = resolve

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        refusal = await refusal_for_host(_connects_to(request), resolve=self._resolve)
        if refusal is not None:
            raise RefusedAddress(refusal)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _connects_to(request: httpx.Request) -> str:
    """The host in the form the connection will resolve.

    ``raw_host`` rather than ``host``: httpx encodes an international name to ASCII once, and the
    encoded form is the one it hands down to the connection.
    """
    return request.url.raw_host.decode("ascii")


def _unread(host: str) -> str:
    return (
        f"syncr will not fetch {host}, because no address it can read answers for that name, and "
        f"syncr does not connect to an address it has not checked. Check the address your "
        f"calendar provider publishes. Every source already configured still syncs."
    )
