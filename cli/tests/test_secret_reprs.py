"""What a credential-carrying object shows when something prints it.

A default dataclass repr is a write waiting for its first caller: a pytest assertion diff, an
f-string in a future error message, or any log line. Nothing prints these today, which is exactly
why the property belongs to the type rather than to every caller's care.
"""

from __future__ import annotations

from syncr_cli.auth.loopback import Redirected
from syncr_cli.auth.tokens import TokenSet

ACCESS = "eyJhbGciOiJFUzI1NiJ9.THE_ACCESS_CLAIMS.THE_SIGNATURE"
REFRESH = "syncrr_THE_REFRESH_TOKEN"
CODE = "syncrc_THE_SINGLE_USE_CODE"


def test_a_token_pairs_repr_carries_neither_token() -> None:
    printed = repr(TokenSet(access_token=ACCESS, refresh_token=REFRESH, expires_in=900, scopes=()))

    assert ACCESS not in printed
    assert REFRESH not in printed


def test_a_token_pairs_repr_still_says_what_it_is() -> None:
    # Hidden, not useless: the shape a developer needs from a repr is which type it is and what it
    # was granted, and neither of those is the secret.
    printed = repr(
        TokenSet(
            access_token=ACCESS,
            refresh_token=REFRESH,
            expires_in=900,
            scopes=("plan:read", "plan:write"),
        )
    )

    assert "TokenSet" in printed
    assert "plan:read" in printed
    assert "900" in printed


def test_a_redirects_repr_carries_no_authorization_code() -> None:
    # A single-use code is a credential until it is exchanged, and the exchange is one request away.
    printed = repr(Redirected(code=CODE, state="a-nonce", error=None, error_description=None))

    assert CODE not in printed
    assert "a-nonce" in printed


def test_the_formatted_form_of_each_is_the_repr() -> None:
    # `f"{value}"` calls `__str__`, which a dataclass does not define, so it falls through to the
    # repr. Asserted because the f-string is the likeliest first caller.
    pair = TokenSet(access_token=ACCESS, refresh_token=REFRESH, expires_in=900, scopes=())

    assert ACCESS not in f"{pair}"
    assert REFRESH not in str(pair)
