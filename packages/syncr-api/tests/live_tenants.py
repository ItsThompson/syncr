"""Seeding and removing a real tenant, for the integration tier.

Every integration test that touches a scoped table needs a tenant that really exists,
because every such table's ``tenant_id`` is a foreign key with ``ON DELETE CASCADE``.
Removing the tenant afterwards is what keeps the suite independent of a developer's
database.

The rows are created through ``UserRepository``, not through ``AccountProvisioner``.
Provisioning is the bootstrap COMMAND's path and it acquires collaborators as the product
grows, most recently a weight-set factory that belongs to plan storage; a fixture for
another feature's tables should not have to satisfy them. The password is hashed by the
real hasher, because a test that signs in needs a hash sign-in will accept.

Each operation comes in two forms, and which one a test wants depends on whose event loop
it is in. An async test owns a loop already, so it awaits :func:`seed_owner` on a
sessionmaker of its own. A test driving the application through ``TestClient`` is
synchronous, and the application's loop is not its to reach into, so it calls
:func:`provision_owner`, which opens a loop and an engine of its own and disposes both: an
asyncpg connection belongs to the loop that opened it.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import delete, func, select

from syncr_api.accounts.models import Tenant
from syncr_api.accounts.passwords import hash_password
from syncr_api.accounts.repository import UserRepository
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database
from tests.boundaries import mapped_classes

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_domain.identifiers import TenantId

PASSWORD = "correct-horse-battery-staple"  # pragma: allowlist secret


def run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    """Run one coroutine on a loop of its own, for a synchronous caller."""
    return asyncio.run(coroutine)


async def seed_owner(sessions: async_sessionmaker[AsyncSession]) -> UserRecord:
    """A tenant and its one user, with an email no other test will collide with."""
    async with sessions() as session, session.begin():
        return await UserRepository(session).create_tenant_with_user(
            email=f"owner-{uuid4().hex}@syncr.test",
            password_hash=hash_password(PASSWORD),
            created_at=utc_now(),
        )


async def delete_tenant(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> None:
    """Delete a tenant, and with it every row that cascades from it."""
    async with sessions() as session, session.begin():
        await session.execute(delete(Tenant).where(Tenant.id == tenant_id))


def provision_owner(database_url: str) -> UserRecord:
    """:func:`seed_owner`, for a synchronous test, on an engine of its own."""

    async def seed() -> UserRecord:
        database = create_database(database_url)
        try:
            return await seed_owner(database.sessionmaker)
        finally:
            await database.engine.dispose()

    return run(seed())


def remove_tenant(database_url: str, tenant_id: TenantId) -> None:
    """:func:`delete_tenant`, for a synchronous test, on an engine of its own."""

    async def remove() -> None:
        database = create_database(database_url)
        try:
            await delete_tenant(database.sessionmaker, tenant_id)
        finally:
            await database.engine.dispose()

    run(remove())


def row_counts(database_url: str, tenant_id: TenantId, source_root: Path) -> dict[str, int]:
    """How many rows this tenant holds in every scoped table the application declares.

    Bounded by the mapped classes rather than by a list, so a table a later feature module adds is
    counted without a caller being extended. Counts rather than values, because a read may
    legitimately touch a column: what it may not do is bring a row into existence.

    Here rather than in one suite because three now compare these counts across a read, and a helper
    imported from a test module couples the two suites that share it.
    """

    async def count() -> dict[str, int]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                counted = {}
                for model in mapped_classes(source_root):
                    scope = getattr(model, "tenant_id", None)
                    table = getattr(model, "__tablename__", None)
                    if scope is None or table is None:
                        continue
                    total = await session.scalar(
                        select(func.count()).select_from(model).where(scope == tenant_id)
                    )
                    counted[str(table)] = int(total or 0)
                return counted
        finally:
            await database.engine.dispose()

    return run(count())
