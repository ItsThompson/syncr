"""Where a preference's owner is confirmed to exist, and which Area its chain climbs to.

Three tables answer for the three kinds of owner and they have no shared parent, so something has
to know which table a kind is read from. That knowledge is ONE mapping here rather than a branch in
the service, in the repository, and again in each route: a fourth kind of owner is an entry in the
mapping, and the suite asserts the mapping covers every kind, so a missing one fails a test rather
than resolving to whichever table a reader looked in first.

**The Area is resolved here too, and an Area owner's is itself.** That is what makes the resolution
chain expressible without the service asking what kind of owner it is holding: every owner has an
Area, the root of every chain is an Area's preference, and for an Area the chain is one link long.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.preferences import PreferenceOwner, PreferenceOwnerKind

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from syncr_api.areas.repository import AreaRepository
    from syncr_api.habits.repository import HabitRepository
    from syncr_api.tasks.repository import TaskRepository
    from syncr_domain.identifiers import AreaId, TenantId


@dataclass(frozen=True, slots=True)
class ResolvedOwner:
    """An owner that exists, and the Area whose preference its chain falls back to."""

    owner: PreferenceOwner
    tenant_id: TenantId
    area_id: AreaId

    @property
    def area_owner(self) -> PreferenceOwner:
        """The Area's own owner, which is how its preference is addressed."""
        return PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=self.area_id)


class PreferenceOwners:
    """Reads whether an owner exists, and answers with the Area its chain climbs to."""

    def __init__(
        self, areas: AreaRepository, habits: HabitRepository, tasks: TaskRepository
    ) -> None:
        self._by_kind: dict[PreferenceOwnerKind, Callable[[UUID], Awaitable[ResolvedOwner | None]]]
        self._by_kind = {
            PreferenceOwnerKind.AREA: self._an_area,
            PreferenceOwnerKind.HABIT: self._a_habit,
            PreferenceOwnerKind.TASK: self._a_task,
        }
        self._areas = areas
        self._habits = habits
        self._tasks = tasks

    @property
    def kinds(self) -> frozenset[PreferenceOwnerKind]:
        """The kinds of owner this lookup can read. Asserted against the vocabulary itself."""
        return frozenset(self._by_kind)

    async def find(self, kind: PreferenceOwnerKind, owner_id: UUID) -> ResolvedOwner | None:
        """The owner this kind and identifier name, or ``None`` if the tenant holds no such row."""
        return await self._by_kind[kind](owner_id)

    async def _an_area(self, owner_id: UUID) -> ResolvedOwner | None:
        found = await self._areas.find(owner_id)
        if found is None:
            return None
        # An Area is the root of its own chain, so it is its own Area.
        return ResolvedOwner(
            owner=PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=found.id),
            tenant_id=found.tenant_id,
            area_id=found.id,
        )

    async def _a_habit(self, owner_id: UUID) -> ResolvedOwner | None:
        found = await self._habits.find(owner_id)
        if found is None:
            return None
        return ResolvedOwner(
            owner=PreferenceOwner(kind=PreferenceOwnerKind.HABIT, id=found.id),
            tenant_id=found.tenant_id,
            area_id=found.area_id,
        )

    async def _a_task(self, owner_id: UUID) -> ResolvedOwner | None:
        found = await self._tasks.find(owner_id)
        if found is None:
            return None
        return ResolvedOwner(
            owner=PreferenceOwner(kind=PreferenceOwnerKind.TASK, id=found.id),
            tenant_id=found.tenant_id,
            area_id=found.area_id,
        )
