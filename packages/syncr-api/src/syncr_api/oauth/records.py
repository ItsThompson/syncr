"""The immutable views of a row that leave the repository, and the rules they carry.

A repository hands back one of these rather than a mapped instance, so a service cannot
trigger a lazy load it did not ask for, cannot mutate a row by assigning to it, and can be
tested against a function returning a frozen dataclass instead of an ORM double.

The usability rules live here rather than in the service, because "is this code still
redeemable" is a property of the row and asking it in three places is how two of them
disagree. Each rule is expressed against an instant the caller supplies, so a test reaches
an expiry by moving time rather than by waiting for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.core.scopes import parse_scopes

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from syncr_api.core.scopes import Scope
    from syncr_domain.identifiers import TenantId


@dataclass(frozen=True, slots=True)
class ClientRecord:
    """A registered client, as persistence knows it."""

    id: str
    name: str
    redirect_uris: tuple[str, ...]
    allowed_scopes: frozenset[Scope]
    loopback_only: bool

    def permits(self, requested: frozenset[Scope]) -> bool:
        """True when every requested scope is one this client may ever hold."""
        return requested <= self.allowed_scopes


@dataclass(frozen=True, slots=True)
class AuthorizationCodeRecord:
    """One authorization code, addressed by the digest of the value the client holds."""

    id: str
    tenant_id: TenantId
    client_id: str
    redirect_uri: str
    scopes: frozenset[Scope]
    code_challenge: str
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None

    def is_redeemable_at(self, now: datetime) -> bool:
        """True when this code has neither been used nor expired.

        Both halves matter and neither is redundant. Expiry alone would leave a code
        redeemable twice inside its minute, which is the replay the single-use rule exists
        to prevent; consumption alone would leave an abandoned code live forever.
        """
        return self.consumed_at is None and now < self.expires_at


@dataclass(frozen=True, slots=True)
class GrantRecord:
    """One tenant's standing authorization of one client."""

    id: UUID
    tenant_id: TenantId
    client_id: str
    scopes: frozenset[Scope]
    authorized_at: datetime
    revoked_at: datetime | None

    @property
    def is_live(self) -> bool:
        """True while this grant still authorizes anything."""
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class RefreshTokenRecord:
    """One refresh token, addressed by the digest of the value the client holds."""

    id: str
    tenant_id: TenantId
    grant_id: UUID
    scopes: frozenset[Scope]
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None
    revoked_at: datetime | None

    @property
    def was_used(self) -> bool:
        """True when this token was already exchanged, so presenting it again is a replay."""
        return self.consumed_at is not None

    def is_exchangeable_at(self, now: datetime) -> bool:
        """True when this token may be exchanged for a fresh pair."""
        return not self.was_used and self.revoked_at is None and now < self.expires_at


def scopes_of(raw: str) -> frozenset[Scope]:
    """The scopes a stored scope string names.

    A stored value was validated before it was written, so an unreadable one is a corrupt
    row rather than a caller's mistake, and it resolves to no authority rather than to an
    error: a row nobody can read must not authorize anything, and it must not answer 500
    either.
    """
    return parse_scopes(raw) or frozenset()
