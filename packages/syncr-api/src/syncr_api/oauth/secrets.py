"""The opaque secrets the flow hands out, and the digest a row stores instead.

Three secrets travel to a client: the authorization code, the refresh token, and (as a
signed claim set, minted elsewhere) the access token. The first two are opaque random
strings, and what the database holds is a SHA-256 digest of each, never the value. So a
database dump, a backup on object storage, or a log line that captured a row yields
nothing replayable.

The digest is unkeyed, unlike the session row's. A session id is a low-entropy-adjacent
lookup key that lives for months, so keying it with the deployment's secret buys
resistance to a precomputed table. These two carry 256 bits from
:func:`secrets.token_urlsafe` and live for a minute and two months respectively, so a
table cannot be precomputed against them and a key would only add a rotation event that
invalidates every live grant.

Each secret carries a prefix naming what it is. That is not decoration: it is what lets a
scanner recognize one in a log, a paste, or a commit, which an undistinguished
random-looking string does not.
"""

from __future__ import annotations

import hashlib
import secrets

# 32 bytes, so guessing one is not a strategy: 256 bits of entropy rendered as 43
# URL-safe base64 characters.
SECRET_ENTROPY_BYTES = 32

# The prefixes, and the two shapes a scanner matches:
#   syncrc_[A-Za-z0-9_-]{43}    an authorization code
#   syncrr_[A-Za-z0-9_-]{43}    a refresh token
AUTHORIZATION_CODE_PREFIX = "syncrc_"
REFRESH_TOKEN_PREFIX = "syncrr_"  # noqa: S105 - the prefix a token carries, not a token

# SHA-256 as 64 lowercase hex characters. This is a digest of a 256-bit secret, so it is
# what a stolen database yields INSTEAD of something replayable, not a secret itself.
DIGEST_LENGTH = 64


def mint_authorization_code() -> str:
    """A fresh authorization code, prefixed so a leak of one is recognizable."""
    return AUTHORIZATION_CODE_PREFIX + secrets.token_urlsafe(SECRET_ENTROPY_BYTES)


def mint_refresh_token() -> str:
    """A fresh refresh token, prefixed so a leak of one is recognizable."""
    return REFRESH_TOKEN_PREFIX + secrets.token_urlsafe(SECRET_ENTROPY_BYTES)


def digest_of(secret: str) -> str:
    """The row identifier for ``secret``: its SHA-256, as 64 lowercase hex characters."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
