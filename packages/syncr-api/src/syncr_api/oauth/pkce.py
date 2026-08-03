"""PKCE (RFC 7636), S256 only.

PKCE is what a public client has instead of a secret. The client keeps a random
``code_verifier``, sends only its SHA-256 digest when it starts the flow, and reveals the
verifier when it exchanges the code. An attacker who intercepts the redirect holds a code
they cannot exchange.

``plain`` is refused, and that is the whole point of requiring the method rather than
accepting whatever is offered. With ``plain`` the challenge IS the verifier, so anyone who
saw the authorize request can exchange the code, which leaves a public client with no
proof of possession at all. The parameter is therefore required, not defaulted: RFC 7636
says a missing ``code_challenge_method`` means ``plain``, so silence would be the weak
mode chosen by omission.
"""

from __future__ import annotations

import hashlib
import secrets
from base64 import urlsafe_b64encode

# RFC 7636 section 4.1: 43 to 128 characters from the unreserved set. The floor is what
# makes the verifier unguessable; the ceiling is what stops an unbounded body reaching the
# digest.
VERIFIER_MIN_LENGTH = 43
VERIFIER_MAX_LENGTH = 128
_VERIFIER_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")

# The S256 challenge is a SHA-256 digest in unpadded URL-safe base64, so its length is
# fixed. A value of any other length was not produced by the transform.
CHALLENGE_LENGTH = 43


def derive_s256_challenge(verifier: str) -> str:
    """The ``S256`` challenge for ``verifier``: its SHA-256, URL-safe base64, unpadded.

    Present here rather than only in the client, because the server needs the same
    transform to verify one and a second implementation of it is a second thing that can
    disagree.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def is_well_formed_challenge(challenge: str) -> bool:
    """True when ``challenge`` could have been produced by the S256 transform."""
    return len(challenge) == CHALLENGE_LENGTH and _is_base64url(challenge)


def is_well_formed_verifier(verifier: str) -> bool:
    """True when ``verifier`` satisfies RFC 7636's length and character rules."""
    return VERIFIER_MIN_LENGTH <= len(verifier) <= VERIFIER_MAX_LENGTH and all(
        character in _VERIFIER_ALPHABET for character in verifier
    )


def verifies(verifier: str, challenge: str) -> bool:
    """True when ``verifier`` is the secret behind ``challenge``.

    Compared in constant time. The comparison is of two public digests rather than of two
    secrets, so timing leaks nothing here; it is constant-time anyway because the rule
    "compare a credential with compare_digest" is worth being unconditional.
    """
    if not is_well_formed_verifier(verifier) or not is_well_formed_challenge(challenge):
        return False
    return secrets.compare_digest(derive_s256_challenge(verifier), challenge)


def _is_base64url(value: str) -> bool:
    return all(character.isalnum() or character in "-_" for character in value)
