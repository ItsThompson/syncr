"""The session credential: its shape, and that the row never holds the token.

The shape is asserted because a leaked session token has to be recognizable: the
scanner that catches one in a log or a commit needs a pattern to match, and a bare
random string does not give it one.
"""

from __future__ import annotations

import re

from syncr_api.accounts.session_tokens import (
    DIGEST_LENGTH,
    TOKEN_PREFIX,
    make_token_digest,
    mint_session_token,
)

# The literal shape a scanner can be written against: the prefix, then 43 URL-safe
# base64 characters, which is what 32 random bytes encode to.
TOKEN_PATTERN = re.compile(rf"^{re.escape(TOKEN_PREFIX)}[A-Za-z0-9_-]{{43}}$")

SIGNING_SECRET = "a-signing-secret-for-this-test"  # pragma: allowlist secret


def test_a_minted_token_matches_the_documented_shape() -> None:
    assert TOKEN_PATTERN.fullmatch(mint_session_token())


def test_two_minted_tokens_differ() -> None:
    assert mint_session_token() != mint_session_token()


def test_the_digest_is_stable_for_one_secret() -> None:
    digest = make_token_digest(SIGNING_SECRET)
    token = mint_session_token()

    assert digest(token) == digest(token)
    assert len(digest(token)) == DIGEST_LENGTH


def test_the_digest_never_contains_the_token() -> None:
    # The row stores this, so a database dump, a backup, or a log line that captured a
    # row must yield nothing replayable.
    token = mint_session_token()

    assert token not in make_token_digest(SIGNING_SECRET)(token)


def test_a_different_secret_produces_a_different_digest() -> None:
    # Which is what makes rotating the signing secret sign every live session out: the
    # same cookie no longer names any row.
    token = mint_session_token()

    assert make_token_digest(SIGNING_SECRET)(token) != make_token_digest("rotated")(token)


def test_the_digest_is_keyed_rather_than_a_bare_hash() -> None:
    import hashlib

    token = mint_session_token()

    assert make_token_digest(SIGNING_SECRET)(token) != hashlib.sha256(token.encode()).hexdigest()
