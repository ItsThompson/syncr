"""The immutable views of an identity row that leave the repository.

A repository hands back one of these rather than a mapped instance. Three things
follow: a service cannot trigger a lazy load it did not ask for, a fake repository in
a service test is a function returning a frozen dataclass instead of an ORM double,
and nothing downstream can mutate a row by assigning to it.

These are not the wire shapes. ``schemas.py`` owns those, so a column added here
does not silently appear in a response.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.accounts.config import SESSION_IDLE_TIMEOUT

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.accounts.session_tokens import SessionId
    from syncr_domain.identifiers import TenantId, UserId


@dataclass(frozen=True, slots=True)
class UserRecord:
    """One user, as persistence knows them."""

    id: UserId
    tenant_id: TenantId
    email: str
    password_hash: str


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """One browser session, as persistence knows it.

    ``id`` is the keyed digest of the cookie's token. The token itself is never
    persisted and therefore never appears here.
    """

    id: SessionId
    tenant_id: TenantId
    user_id: UserId
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None

    def usable_until(self) -> datetime:
        """The instant this session stops working: the earlier of two rules.

        The idle window slides with every use, so it is derived from ``last_seen_at``
        rather than stored; the absolute cap does not move. Deriving it means the two
        rules cannot disagree, and that a stored expiry can never have been slid past
        the cap by a bug.
        """
        return min(self.expires_at, self.last_seen_at + SESSION_IDLE_TIMEOUT)

    def is_usable_at(self, now: datetime) -> bool:
        """True when this session still authenticates its user at ``now``."""
        return self.revoked_at is None and now < self.usable_until()
