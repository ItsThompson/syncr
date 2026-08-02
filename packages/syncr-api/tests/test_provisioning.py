"""Provisioning the first account, which is the one operation with no principal.

Three properties matter for a command an operator runs once during a first deployment and
then possibly again by accident. It must refuse a password too weak for an account that is
reachable from the public internet, it must be safe to run twice: reporting the existing
account rather than creating a second one or failing on a constraint, and the tenant it
creates must come out able to be planned for, which means holding an active weight set.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.accounts.config import MINIMUM_PASSWORD_LENGTH
from syncr_api.accounts.passwords import hash_password, verify_password
from syncr_api.accounts.provisioning import AccountProvisioner, BootstrapRejected
from syncr_api.accounts.records import UserRecord
from syncr_api.accounts.repository import UserRepository
from syncr_api.learned.config import FIRST_WEIGHT_SET_VERSION, HAND_TUNED, P0_WEIGHTS
from syncr_api.learned.records import WeightSetRecord
from syncr_api.learned.repository import WeightSetRepository

if TYPE_CHECKING:
    from syncr_domain.identifiers import TenantId, UserId

EMAIL = "owner@syncr.test"
PASSWORD = "correct-horse-battery-staple"  # pragma: allowlist secret
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)


class FakeUserRepository(UserRepository):
    """Creates and finds users in a dict, recording what a real one would have written."""

    def __init__(self, existing: list[UserRecord] | None = None) -> None:
        self.rows = {user.email: user for user in existing or []}

    async def find_by_email(self, email: str) -> UserRecord | None:
        return self.rows.get(email)

    async def find(self, user_id: UserId) -> UserRecord | None:
        return next((user for user in self.rows.values() if user.id == user_id), None)

    async def create_tenant_with_user(
        self, *, email: str, password_hash: str, created_at: datetime
    ) -> UserRecord:
        assert created_at == NOW
        created = UserRecord(
            id=uuid4(), tenant_id=uuid4(), email=email, password_hash=password_hash
        )
        self.rows[email] = created
        return created


class FakeWeightSetRepository(WeightSetRepository):
    """Records the version-1 seed a real one would have written, per tenant."""

    def __init__(self, tenant_id: TenantId, seeded: dict[TenantId, WeightSetRecord]) -> None:
        self._seeded_tenant_id = tenant_id
        self.seeded = seeded

    async def seed_hand_tuned(self, *, at: datetime) -> WeightSetRecord:
        assert at == NOW
        record = WeightSetRecord(
            tenant_id=self._seeded_tenant_id,
            version=FIRST_WEIGHT_SET_VERSION,
            active=True,
            origin=HAND_TUNED,
            duration_multiplier={},
            time_of_day_fitness={},
            skip_probability={},
            fitted_at=None,
            maturity=[],
            created_at=at,
            **P0_WEIGHTS,
        )
        self.seeded[self._seeded_tenant_id] = record
        return record


def provisioner(
    users: FakeUserRepository, seeded: dict[TenantId, WeightSetRecord] | None = None
) -> AccountProvisioner:
    recorded = {} if seeded is None else seeded
    return AccountProvisioner(
        users=users,
        clock=lambda: NOW,
        weight_sets=lambda tenant_id: FakeWeightSetRepository(tenant_id, recorded),
    )


async def test_provisioning_creates_a_tenant_and_its_user() -> None:
    users = FakeUserRepository()

    account = await provisioner(users).provision(EMAIL, PASSWORD)

    assert account.created is True
    assert account.email == EMAIL
    assert account.tenant_id is not None
    assert account.user_id is not None


async def test_the_created_user_can_be_verified_with_the_password_given() -> None:
    # The whole point of the command: the credential it writes is the one sign-in reads.
    users = FakeUserRepository()

    await provisioner(users).provision(EMAIL, PASSWORD)

    assert verify_password(PASSWORD, users.rows[EMAIL].password_hash) is True


def test_the_password_is_never_stored_as_written() -> None:
    assert PASSWORD not in hash_password(PASSWORD)


@pytest.mark.parametrize("presented", ["Owner@Syncr.TEST", "  owner@syncr.test  "])
async def test_the_email_is_stored_normalized(presented: str) -> None:
    # Stored in the form sign-in compares against, or the account could never be used.
    users = FakeUserRepository()

    account = await provisioner(users).provision(presented, PASSWORD)

    assert account.email == EMAIL
    assert set(users.rows) == {EMAIL}


async def test_running_it_again_reports_the_existing_account_and_creates_nothing() -> None:
    existing = UserRecord(
        id=uuid4(), tenant_id=uuid4(), email=EMAIL, password_hash=hash_password(PASSWORD)
    )
    users = FakeUserRepository([existing])

    account = await provisioner(users).provision(EMAIL, "a-completely-different-password")

    assert account.created is False
    assert account.user_id == existing.id
    assert account.tenant_id == existing.tenant_id
    assert users.rows[EMAIL].password_hash == existing.password_hash


async def test_a_short_password_is_refused_and_nothing_is_created() -> None:
    users = FakeUserRepository()

    with pytest.raises(BootstrapRejected, match=str(MINIMUM_PASSWORD_LENGTH)):
        await provisioner(users).provision(EMAIL, "short")

    assert users.rows == {}


async def test_a_password_at_the_minimum_length_is_accepted() -> None:
    # The boundary, so the check is not off by one in the direction that locks an operator
    # out of their own deployment.
    users = FakeUserRepository()

    account = await provisioner(users).provision(EMAIL, "x" * MINIMUM_PASSWORD_LENGTH)

    assert account.created is True


async def test_the_created_tenant_holds_an_active_hand_tuned_weight_set() -> None:
    # Without it the first user has no weights to solve under, and every revision's
    # `weight_set_version` would name a row that does not exist. The migration seeds the
    # tenants that existed when it ran, which on a first deployment is none.
    users = FakeUserRepository()
    seeded: dict[TenantId, WeightSetRecord] = {}

    account = await provisioner(users, seeded).provision(EMAIL, PASSWORD)

    weights = seeded[account.tenant_id]
    assert weights.version == FIRST_WEIGHT_SET_VERSION
    assert weights.active is True
    assert weights.origin == HAND_TUNED
    assert weights.deadline_risk == P0_WEIGHTS["deadline_risk"]


async def test_an_account_that_already_exists_is_not_seeded_again() -> None:
    # A second seed for one tenant is rejected by the primary key, so a re-run must not
    # attempt one: the command's whole point is that running it twice is safe.
    existing = UserRecord(
        id=uuid4(), tenant_id=uuid4(), email=EMAIL, password_hash=hash_password(PASSWORD)
    )
    seeded: dict[TenantId, WeightSetRecord] = {}

    await provisioner(FakeUserRepository([existing]), seeded).provision(EMAIL, PASSWORD)

    assert seeded == {}
