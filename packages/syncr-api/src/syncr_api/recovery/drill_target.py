"""Which database a drill's evidence may be written to, decided from what the database holds.

A restore drill needs rows it can afford to lose, so something has to write invented ones. On a
deployed host the database it would reach is the live one, and nothing about the connection says so:
`docker-compose.yml` names the project `syncr` on a workstation and on a host alike, the database is
`syncr` in both, and the URL a container reads names the same in-network Postgres either way. So the
project, the name and the URL are all silent here, and the one fact that is not silent is what the
database already holds.

**The rule: every tenant this database holds is the drill's own.** A deployment holds the operator's
tenant, because `syncr-bootstrap-user` is what a first deployment runs before the product serves
anything, so refusing a foreign tenant refuses a deployment. A drill's own database holds no tenant
at all the first time and only the drill's every later time, which is what lets one rule admit a
repeat run.

**What this cannot do, beside what it can.** A database holding no tenant is admitted, so a
deployment between its migration one-shot and its bootstrap command is inside the bound: there is
nothing there to overwrite, and what the miss costs is a drill tenant beside the operator's own
rather than invented rows inside real plan history. It reads no host fact, so it cannot tell a
workstation from a deployed host at all; the refusal carried by the seeding recipes reads two host
facts and answers that question, and it is a `just` dependency, so it cannot see a caller that never
runs `just`. Two guards, two questions, and this is the one that travels with the write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.accounts.repository import TenantRepository, UserRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_domain.identifiers import TenantId


class NotTheDrillsDatabase(Exception):
    """The target holds a tenant the drill did not create, so nothing is written to it."""


async def foreign_tenants(session: AsyncSession, *, drill_email: str) -> tuple[TenantId, ...]:
    """Every tenant here whose user is not the drill's own, in the order the ids were read.

    A tenant carrying no user at all is foreign too. The drill's own tenant always carries one,
    because provisioning creates the pair in one transaction, so a tenant without one was made by
    something else and the failure direction is a refusal.
    """
    users = UserRepository(session)
    found: list[TenantId] = []
    for tenant_id in await TenantRepository(session).list_ids():
        held = await users.find_by_tenant(tenant_id)
        if held is None or held.email != drill_email:
            found.append(tenant_id)
    return tuple(found)


async def require_the_drills_own_database(session: AsyncSession, *, drill_email: str) -> None:
    """Raise :class:`NotTheDrillsDatabase` unless every tenant here is the drill's own."""
    foreign = await foreign_tenants(session, drill_email=drill_email)
    if not foreign:
        return
    raise NotTheDrillsDatabase(
        f"this database holds {len(foreign)} tenant(s) the drill did not create "
        f"({', '.join(str(one) for one in foreign)}), so it is somebody's real plan history rather "
        f"than a drill's scratch copy. A drill's own holds one tenant, {drill_email}. "
        "Nothing was written. On a deployed host run `just restore-drill`, which uses the real "
        "bucket and the real key and needs no seed at all."
    )
