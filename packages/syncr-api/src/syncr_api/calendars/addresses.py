"""The address ranges syncr will not fetch, stated once.

A calendar feed is published on the public internet. An address inside the ranges below is
not a publisher: it is this deployment's own network, where Postgres, the api, the worker and
the host's own metadata service answer. Fetching one would make a user-supplied address a
request syncr issues from inside its own perimeter.

The ranges are stated here and nowhere else, and the rule is stated over callers rather than over a
roster of them: any caller that decides whether syncr may fetch an address reads this module, and
none restates the ranges. The normalizer is one such caller, and it asks of a literal a user pasted,
before storing anything. A caller reading the address a socket will connect to would ask the same
question of a resolved address, and must read the same rows: an accept-list and a redirect check
stated separately are how the two come to disagree, while both stay green.

Two limits of a literal check, both closed by asking the same question of a resolved address:
``ipaddress`` reads only the dotted and colon spellings, so the decimal and hexadecimal forms
of an address that a resolver still accepts are not literals here; and a name is not an
address at all.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from ipaddress import IPv4Network, IPv6Network

type FetchAddress = IPv4Address | IPv6Address

# Stated as networks because ``ipaddress`` names neither in a property this module can read:
# ``is_private`` holds over fc00::/7 without naming it, and answers False over the whole of
# the deprecated site-local block.
UNIQUE_LOCAL: Final = ip_network("fc00::/7")
SITE_LOCAL: Final = ip_network("fec0::/10")


def _within(network: IPv4Network | IPv6Network) -> Callable[[FetchAddress], bool]:
    """Membership of one stated network, which is False for an address of the other family."""
    return lambda address: address in network


# The ranges, most specific first, so the reason a refusal states is the most informative one
# that holds. ``is_private`` is last because it holds over four of the rows above it.
REFUSED_RANGES: Final[tuple[tuple[str, Callable[[FetchAddress], bool]], ...]] = (
    ("the unspecified address", lambda address: address.is_unspecified),
    ("a loopback address", lambda address: address.is_loopback),
    ("a link-local address", lambda address: address.is_link_local),
    ("a unique-local address", _within(UNIQUE_LOCAL)),
    ("a site-local address", _within(SITE_LOCAL)),
    ("a multicast address", lambda address: address.is_multicast),
    ("a private-range address", lambda address: address.is_private),
)


def refusal_of(address: FetchAddress) -> str | None:
    """Why syncr will not fetch ``address``, or ``None`` when it will.

    One sentence for both askers, so the answer a user reads when a feed is added is the
    answer they read when a stored feed resolves inward.
    """
    for range_name, holds in REFUSED_RANGES:
        if holds(address):
            return _refusal(address, range_name)
    return None


def address_in(host: str) -> FetchAddress | None:
    """The address literal ``host`` holds, or ``None`` when it names something to resolve."""
    for candidate in _spellings(host):
        try:
            return ip_address(candidate)
        except ValueError:
            continue
    return None


def _spellings(host: str) -> Iterator[str]:
    """Every way a host field could be spelling one address literal.

    Bracketed is the only spelling of an IPv6 host RFC 3986 admits, and the only one
    ``SplitResult.hostname`` reads: it answers ``None`` for a bare ``::1``, which is why the
    host is read as written here rather than taken from that property.
    """
    yield host
    if host.startswith("["):
        yield host[1:].partition("]")[0]
    yield host.rpartition(":")[0]


def _refusal(address: FetchAddress, range_name: str) -> str:
    return (
        f"syncr will not fetch {address}, because it is {range_name} rather than an address on "
        f"the public internet, where a calendar publisher serves a feed. Paste the address your "
        f"calendar provider publishes. Every source already configured still syncs."
    )
