"""The session credential: what the cookie carries and what the row stores.

The cookie carries an opaque random token, never a signed claim set. A self-contained
token cannot be revoked before it expires, and sign-out has to take effect
immediately, so the server keeps the authority and the cookie is only a pointer to it.

What the row stores is a keyed digest of that token, not the token. A database dump,
a backup on object storage, or a log line that captured a row therefore yields nothing
that can be replayed: the token is only ever in the cookie and in the request that
carries it. The key is the deployment's session signing secret, which is why rotating
that secret signs every live session out.

The token's literal shape is ``syncrs_`` followed by 43 URL-safe base64 characters
(32 random bytes). The prefix is not decoration: it is what lets a scanner recognize a
leaked session token in a log, a paste, or a commit, which an undistinguished
random-looking string does not.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# 32 bytes, so the token has 256 bits of entropy and guessing one is not a strategy.
TOKEN_ENTROPY_BYTES = 32
TOKEN_PREFIX = "syncrs_"  # noqa: S105 - the prefix a token carries, not a token

# HMAC-SHA256, rendered as 64 lowercase hex characters. Keyed rather than a bare
# hash so a stolen digest cannot be attacked with a precomputed table.
DIGEST_LENGTH = 64

type SessionToken = str
type SessionId = str
type TokenDigest = Callable[[SessionToken], SessionId]


def mint_session_token() -> SessionToken:
    """A fresh session token, prefixed so a leak of one is recognizable."""
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def make_token_digest(signing_secret: str) -> TokenDigest:
    """Build the token-to-row-id function for one deployment's signing secret.

    A factory rather than a module function taking the secret each time: the secret is
    resolved once, at wiring time, so no call site has to be trusted to pass the right
    one.
    """
    key = signing_secret.encode("utf-8")

    def digest(token: SessionToken) -> SessionId:
        return hmac.new(key, token.encode("utf-8"), hashlib.sha256).hexdigest()

    return digest
