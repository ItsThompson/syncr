"""The origin check: which requests may change state, and from where.

Two properties matter and both are asserted. A safe method is never rejected, because
this check is about forged state changes and rejecting reads would break every probe and
healthcheck. An unsafe method with no stated origin IS rejected, because a browser sends
one on every unsafe request and something that does not is not the browser this
deployment serves.
"""

from __future__ import annotations

import pytest

from syncr_api.accounts.origin import UNSAFE_METHODS, is_origin_trusted

ALLOWED = ("http://localhost:5173", "https://syncr.example")


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "get"])
def test_a_safe_method_is_never_rejected(method: str) -> None:
    assert is_origin_trusted(method, origin=None, referer=None, allowed=ALLOWED) is True
    assert is_origin_trusted(method, origin="https://evil.test", referer=None, allowed=ALLOWED)


@pytest.mark.parametrize("method", sorted(UNSAFE_METHODS))
def test_an_unsafe_method_from_an_allowed_origin_is_trusted(method: str) -> None:
    assert is_origin_trusted(method, origin=ALLOWED[0], referer=None, allowed=ALLOWED) is True


@pytest.mark.parametrize("method", sorted(UNSAFE_METHODS))
def test_an_unsafe_method_from_another_origin_is_rejected(method: str) -> None:
    assert (
        is_origin_trusted(method, origin="https://evil.test", referer=None, allowed=ALLOWED)
        is False
    )


def test_an_unsafe_method_with_no_stated_origin_is_rejected() -> None:
    assert is_origin_trusted("POST", origin=None, referer=None, allowed=ALLOWED) is False


def test_the_referer_is_read_when_no_origin_is_sent() -> None:
    # The documented fallback for the browsers that historically omitted Origin on a
    # same-origin request. Only the origin component is read.
    trusted = is_origin_trusted(
        "POST", origin=None, referer="https://syncr.example/week/2026-W07", allowed=ALLOWED
    )

    assert trusted is True


def test_a_referer_from_another_origin_is_rejected() -> None:
    rejected = is_origin_trusted(
        "POST", origin=None, referer="https://evil.test/syncr.example", allowed=ALLOWED
    )

    assert rejected is False


def test_the_origin_header_wins_over_the_referer() -> None:
    # A forged request can carry any Referer it likes; the browser sets Origin.
    rejected = is_origin_trusted(
        "POST", origin="https://evil.test", referer=ALLOWED[0], allowed=ALLOWED
    )

    assert rejected is False


@pytest.mark.parametrize(
    "configured",
    ["https://syncr.example/", "HTTPS://Syncr.Example", "https://syncr.example"],
)
def test_a_configured_origin_is_compared_in_one_normalized_form(configured: str) -> None:
    # An operator writing a trailing slash or a capital letter must not lock themselves
    # out of every mutation.
    assert is_origin_trusted(
        "POST", origin="https://syncr.example", referer=None, allowed=(configured,)
    )


def test_nothing_is_trusted_when_no_origin_is_configured() -> None:
    assert is_origin_trusted("POST", origin=ALLOWED[0], referer=None, allowed=()) is False


def test_a_port_is_part_of_the_origin() -> None:
    # http://localhost:5173 and http://localhost:8000 are different origins, so the dev
    # server being allowed must not allow everything on localhost.
    assert (
        is_origin_trusted("POST", origin="http://localhost:8000", referer=None, allowed=ALLOWED)
        is False
    )
