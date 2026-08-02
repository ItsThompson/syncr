"""Creating the first tenant and its user. Deliberately not a service method.

P0 has no sign-up screen and no account-creation route: multi-user onboarding is a
later concern, and a screen exactly one person would ever see is a screen not worth
building. So the first tenant and user are created by a documented operator command,
which is what ``docs/runbooks/bootstrap-first-user.md`` describes.

This is the one account operation with no principal, because it is the trust root:
there is nobody to authorize against before the first user exists. It lives outside
``service.py`` for that reason. Every method in ``service.py`` takes a principal, with
no exception and therefore no exemption list, and this file is why that stays true.

It also seeds the tenant's weight set, in the same transaction. A tenant with no active
weight set is a tenant nothing can plan for: ``PlanRevision.weight_set_version`` is
non-optional from the first revision onwards, and the migration that created the table
seeded only the tenants that existed when it ran. Creating the tenant is the one moment that
can guarantee the row, so it is done here rather than by whatever reads it first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.accounts.config import MINIMUM_PASSWORD_LENGTH
from syncr_api.accounts.emails import normalize_email
from syncr_api.accounts.passwords import hash_password_in_thread
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from syncr_api.accounts.repository import UserRepository
    from syncr_api.core.clock import Clock
    from syncr_api.learned.repository import WeightSetRepository
    from syncr_domain.identifiers import TenantId, UserId

_log = get_logger("syncr.accounts")

# A weight-set repository is scoped to a tenant at construction, and the tenant does not
# exist until this command creates it, so the provisioner takes the factory rather than the
# repository.
type WeightSetFactory = Callable[[TenantId], WeightSetRepository]


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

    def __init__(self, users: UserRepository, clock: Clock, weight_sets: WeightSetFactory) -> None:
        self._users = users
        self._clock = clock
        self._weight_sets = weight_sets

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

        created_at = self._clock()
        user = await self._users.create_tenant_with_user(
            email=normalized,
            password_hash=await hash_password_in_thread(password),
            created_at=created_at,
        )
        weights = await self._weight_sets(user.tenant_id).seed_hand_tuned(at=created_at)
        _log.info(
            "accounts.bootstrap.provisioned",
            tenant_id=str(user.tenant_id),
            user_id=str(user.id),
            weight_set_version=weights.version,
        )
        return ProvisionedAccount(
            tenant_id=user.tenant_id,
            user_id=user.id,
            email=user.email,
            created=True,
        )
