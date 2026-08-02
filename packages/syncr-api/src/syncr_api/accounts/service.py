"""The session service: where authorization for the session resource is enforced.

Every method here takes a principal as its FIRST argument and checks it against the
row's own tenant before acting. That is the whole authorization boundary: the HTTP
layer validates a body and resolves who is asking, this layer decides whether they may,
and the repository decides nothing.

A row belonging to another tenant raises 404 rather than 403, so a caller cannot use
the status to learn that a session id exists. ``authorize_tenant`` is the one place
that rule is implemented, so it cannot be applied inconsistently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.core.errors import NotFound
from syncr_api.core.principal import authorize_tenant
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.accounts.repository import SessionRepository, UserRepository
    from syncr_api.accounts.session_tokens import SessionId
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_domain.identifiers import TenantId, UserId

SESSION_RESOURCE = "session"
USER_RESOURCE = "user"

_log = get_logger("syncr.accounts")


@dataclass(frozen=True, slots=True)
class SessionDescription:
    """Who the caller is and how long this session has left."""

    tenant_id: TenantId
    user_id: UserId
    email: str
    expires_at: datetime


class SessionService:
    """Read and revoke the session the caller presented."""

    def __init__(self, sessions: SessionRepository, users: UserRepository, clock: Clock) -> None:
        self._sessions = sessions
        self._users = users
        self._clock = clock

    @measured("accounts")
    async def describe(self, principal: Principal, session_id: SessionId) -> SessionDescription:
        """The current principal, with the email and expiry the shell displays."""
        session = await self._sessions.find(session_id)
        if session is None:
            raise NotFound(f"No {SESSION_RESOURCE} matches that identifier.")
        authorize_tenant(principal, session.tenant_id, resource=SESSION_RESOURCE)

        user = await self._users.find(session.user_id)
        if user is None:
            raise NotFound(f"No {USER_RESOURCE} matches that identifier.")
        authorize_tenant(principal, user.tenant_id, resource=USER_RESOURCE)

        return SessionDescription(
            tenant_id=session.tenant_id,
            user_id=session.user_id,
            email=user.email,
            expires_at=session.usable_until(),
        )

    @measured("accounts")
    async def log_out(self, principal: Principal, session_id: SessionId) -> None:
        """Revoke server-side, so the cookie alone cannot be replayed afterwards."""
        session = await self._sessions.find(session_id)
        if session is None:
            raise NotFound(f"No {SESSION_RESOURCE} matches that identifier.")
        authorize_tenant(principal, session.tenant_id, resource=SESSION_RESOURCE)

        await self._sessions.revoke(session_id, self._clock())
        _log.info(
            "accounts.sign_out.completed",
            tenant_id=str(principal.tenant_id),
            user_id=str(principal.user_id),
        )
