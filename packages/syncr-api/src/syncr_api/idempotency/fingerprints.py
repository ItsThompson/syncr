"""The two derived values the guard needs, both pure.

``request_fingerprint`` is what distinguishes "the same request again" from "a different
request under a key someone reused". It is taken over the raw body bytes, before parsing, so
two bodies that differ only in whitespace or key order are two different requests. That is
the conservative direction: a false difference answers 422 and asks the client for a new
key, while a false match would replay the wrong response.

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


def request_fingerprint(body: bytes) -> str:
    """The hash a retry has to match to be a retry rather than a different request."""
    return sha256(body).hexdigest()


def lock_token(tenant_id: TenantId, route: str, key: str) -> int:
    """The advisory-lock number for one tenant's key on one route."""
    digest = blake2b(f"{tenant_id}:{route}:{key}".encode(), digest_size=_TOKEN_BYTES).digest()
    return int.from_bytes(digest, "big") - _SIGNED_64_BIT_OFFSET
