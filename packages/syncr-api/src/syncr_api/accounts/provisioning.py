"""Creating the first tenant and its user. Deliberately not a service method.

P0 has no sign-up screen and no account-creation route: multi-user onboarding is a
later concern, and a screen exactly one person would ever see is a screen not worth
building. So the first tenant and user are created by a documented operator command,
which is what ``docs/runbooks/bootstrap-first-user.md`` describes.

This is the one account operation with no principal, because it is the trust root:
there is nobody to authorize against before the first user exists. It lives outside
``service.py`` for that reason. Every method in ``service.py`` takes a principal, with
no exception and therefore no exemption list, and this file is why that stays true.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.accounts.config import MINIMUM_PASSWORD_LENGTH
from syncr_api.accounts.emails import normalize_email
from syncr_api.accounts.passwords import hash_password
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from syncr_api.accounts.repository import UserRepository
    from syncr_api.core.clock import Clock
    from syncr_domain.identifiers import TenantId, UserId

_log = get_logger("syncr.accounts")


class BootstrapRejected(Exception):
    """The requested account cannot be created, with a reason an operator can act on.

    Not a :class:`~syncr_api.core.errors.SyncrError`: nothing here is reachable over
    HTTP, so a wire status and a problem-details shape would be answering a question
    nobody asked. The command prints the message and exits non-zero.
    """


@dataclass(frozen=True, slots=True)
class ProvisionedAccount:
    """What was created, or what already existed."""

    tenant_id: TenantId
    user_id: UserId
    email: str
    created: bool


class AccountProvisioner:
    """Creates the first tenant and user, and says so if one already exists."""

    def __init__(self, users: UserRepository, clock: Clock) -> None:
        self._users = users
        self._clock = clock

    async def provision(self, email: str, password: str) -> ProvisionedAccount:
        """Create a tenant and its one user, or report the existing one.

        Idempotent by design: an operator re-running the command after a partial
        deployment gets "this already exists" rather than a second account or a
        traceback. Creating a duplicate is the one outcome that must not happen, since
        the unique email index would reject it at commit and the message would name a
        constraint rather than the situation.
        """
        normalized = normalize_email(email)
        if len(password) < MINIMUM_PASSWORD_LENGTH:
            message = (
                f"the password is shorter than {MINIMUM_PASSWORD_LENGTH} characters, and "
                "this account is reachable from the public internet"
            )
            raise BootstrapRejected(message)

        existing = await self._users.find_by_email(normalized)
        if existing is not None:
            return ProvisionedAccount(
                tenant_id=existing.tenant_id,
                user_id=existing.id,
                email=existing.email,
                created=False,
            )

        user = await self._users.create_tenant_with_user(
            email=normalized,
            password_hash=hash_password(password),
            created_at=self._clock(),
        )
        _log.info(
            "accounts.bootstrap.provisioned",
            tenant_id=str(user.tenant_id),
            user_id=str(user.id),
        )
        return ProvisionedAccount(
            tenant_id=user.tenant_id,
            user_id=user.id,
            email=user.email,
            created=True,
        )
