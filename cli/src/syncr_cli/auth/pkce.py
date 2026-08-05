"""PKCE (RFC 7636), the client half. S256 only.

PKCE is what this client has instead of a secret. It keeps a random ``code_verifier``, sends
only the SHA-256 digest of it when it starts the flow, and reveals the verifier when it exchanges
the code. Anyone who intercepts the redirect holds a code they cannot exchange.

``code_challenge_method`` is sent explicitly and is always ``S256``. RFC 7636 reads an absent
method as ``plain``, where the challenge IS the verifier and proves nothing, so silence would be
the weak mode chosen by omission. The Authorization Server refuses ``plain`` and advertises
``S256`` as the only method it supports; this client never offers the choice.

The transform is spelled here rather than imported because this package ships nothing
server-side: the api owns its own copy for verification, and the two are crossed against each
other by the RFC's published worked example, which both sides assert.
"""

from __future__ import annotations

import hashlib
import secrets
from base64 import urlsafe_b64encode
from typing import Final

CODE_CHALLENGE_METHOD_S256: Final = "S256"

# 32 bytes rendered as 43 URL-safe base64 characters, which is RFC 7636's floor for a verifier
# and 256 bits of entropy. The ceiling is 128 characters; nothing is gained by approaching it.
VERIFIER_ENTROPY_BYTES: Final = 32


def generate_verifier() -> str:
    """A fresh ``code_verifier``, held in memory for the length of one flow and never stored."""
    return secrets.token_urlsafe(VERIFIER_ENTROPY_BYTES)


def derive_challenge(verifier: str) -> str:
    """The ``S256`` challenge for ``verifier``: its SHA-256, URL-safe base64, unpadded."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).decode("ascii").rstrip("=")
