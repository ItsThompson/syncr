"""The two derived values the guard needs, both pure.

``request_fingerprint`` is what distinguishes "the same request again" from "a different
request under a key someone reused". It is taken over the addressed path and the raw body
bytes, before parsing, so two bodies that differ only in whitespace or key order are two
different requests. That is the conservative direction: a false difference answers 422 and
asks the client for a new key, while a false match would replay the wrong response.

The path is in the hash because the claim's identity does not carry it: a claim is
``(tenant_id, route, idempotency_key)`` and ``route`` names the handler, not the resource.
Without it, a bodyless route addressed by a path parameter hashes identically for every
resource it can name, and one key sent to two of them answers the second request out of the
first's stored row.

The path is framed by its own digest rather than concatenated with the body, so a path cannot
be confused with a shorter path plus the first bytes of a body. A separator byte would not do:
the server hands over a percent-decoded path, which may hold any character.

``lock_token`` is the number a transaction-scoped advisory lock is taken on. Postgres locks
integers, not strings, so the tenant, the route, and the key are hashed into one. A
collision between two different keys costs a spurious 409 with a ``Retry-After``, and a
64-bit digest makes that unreachable in practice for one user's request volume.
"""

from __future__ import annotations

from hashlib import blake2b, sha256
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syncr_domain.identifiers import TenantId

# Postgres advisory locks take a signed 64-bit integer.
_TOKEN_BYTES = 8
_SIGNED_64_BIT_OFFSET = 1 << 63


def request_fingerprint(path: str, body: bytes) -> str:
    """The hash a retry has to match to be a retry rather than a different request."""
    return sha256(sha256(path.encode()).digest() + body).hexdigest()


def lock_token(tenant_id: TenantId, route: str, key: str) -> int:
    """The advisory-lock number for one tenant's key on one route."""
    digest = blake2b(f"{tenant_id}:{route}:{key}".encode(), digest_size=_TOKEN_BYTES).digest()
    return int.from_bytes(digest, "big") - _SIGNED_64_BIT_OFFSET
