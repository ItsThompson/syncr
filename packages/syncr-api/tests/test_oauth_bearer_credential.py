"""Reading the bearer credential out of a request, and the detail a 401 carries.

The parsing rules are small and each one is a way a legitimate client fails to authenticate:
RFC 7235 makes the scheme case-insensitive, so a client sending ``bearer`` is not wrong, and a
header with a scheme and no credential is a client bug that must read as "no token presented"
rather than as a token that happens to be empty.

The 401 itself is asserted through HTTP in ``test_oauth_flow_integration.py``, where the
dependency runs on a route and the ``WWW-Authenticate`` header reaches the wire.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from syncr_api.oauth.errors import bearer_challenge
from syncr_api.oauth.injection import AUTHORIZATION_HEADER, MISSING_BEARER_DETAIL, read_bearer_token

TOKEN = "eyJhbGciOiJFUzI1NiJ9.eyJzdWIiOiJhIn0.signature"  # pragma: allowlist secret


def request_presenting(header: str | None) -> Request:
    """A request carrying ``header`` as its ``Authorization``, or carrying none."""
    headers = [] if header is None else [(AUTHORIZATION_HEADER.encode(), header.encode())]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (f"Bearer {TOKEN}", TOKEN),
        (f"bearer {TOKEN}", TOKEN),
        (f"BEARER {TOKEN}", TOKEN),
        (f"Bearer   {TOKEN}  ", TOKEN),
        (None, None),
        ("", None),
        (TOKEN, None),
        ("Bearer", None),
        ("Bearer ", None),
        ("Bearer    ", None),
        (f"Basic {TOKEN}", None),
    ],
    ids=[
        "the scheme as the rfc spells it",
        "lower case, which rfc 7235 permits",
        "upper case",
        "padded",
        "no header at all",
        "an empty header",
        "a credential with no scheme",
        "a scheme with nothing after it",
        "a scheme with an empty credential",
        "a scheme with only spaces after it",
        "another scheme",
    ],
)
def test_what_counts_as_a_presented_access_token(header: str | None, expected: str | None) -> None:
    assert read_bearer_token(request_presenting(header)) == expected


def test_the_challenge_names_the_scheme_a_client_should_present() -> None:
    # RFC 6750 section 3: without this a client learns only that it was refused.
    assert bearer_challenge() == {"WWW-Authenticate": 'Bearer realm="syncr"'}


def test_the_missing_credential_detail_says_what_to_present() -> None:
    # The message is the whole interface of a client that authenticated the wrong way.
    assert "Authorization: Bearer" in MISSING_BEARER_DETAIL
