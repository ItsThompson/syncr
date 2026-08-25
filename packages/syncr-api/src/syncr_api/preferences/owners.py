"""Where a preference's owner is confirmed to exist, and which Area its chain climbs to.

Three tables answer for the three kinds of owner and they have no shared parent, so something has
to know which table a kind is read from. That knowledge is ONE mapping here rather than a branch in
the service, in the repository, and again in each route: a fourth kind of owner is an entry in the
mapping, and the suite asserts the mapping covers every kind, so a missing one fails a test rather
than resolving to whichever table a reader looked in first.

**The Area is resolved here too, and an Area owner's is itself.** That is what makes the resolution
chain expressible without the service asking what kind of owner it is holding: every owner has an
Area, and :meth:`PreferenceOwners.ancestry` walks from that Area up to the root of the hierarchy.

**The ancestry is one read and one walk, nearest first.** :meth:`ancestry` loads the tenant's Areas
in ONE statement and climbs ``parent_id`` in memory rather than issuing a query per level. The walk
carries a visited set and a stated depth cap, so a cycle in ``areas.parent_id`` is refused as an
:class:`UnreadableAreaAncestry` that names the Areas rather than as a request fault: nothing the
caller sent is wrong, and no request can write such a row. The Areas module confirms a declared
parent exists and an Area never moves, so only data written around the application can close a loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from syncr_domain.errors import DomainError
from syncr_domain.preferences import PreferenceOwner, PreferenceOwnerKind

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from syncr_api.areas.records import AreaRecord
    from syncr_api.areas.repository import AreaRepository
    from syncr_api.habits.repository import HabitRepository
    from syncr_api.tasks.repository import TaskRepository
    from syncr_domain.identifiers import AreaId, TenantId

# How deep an Area ancestry the walk will follow. A depth past this cannot come from a request:
# it names either a cycle the visited set did not reach or a hierarchy no screen authors, and
# both are stored-data faults refused where they are read.
MAX_AREA_DEPTH: Final = 16


class UnreadableAreaAncestry(DomainError):
    """The stored ``areas.parent_id`` rows cannot be walked to the root.

    Its own type rather than a request error, because nothing a caller sent is wrong: a cycle is
    written around the application or not at all. Uncaught by the boundary's mappings, it reads
    as the server fault it is.
    """


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
    """Reads whether an owner exists, and walks the Area ancestry its chain climbs."""

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

    async def ancestry(self, area_id: AreaId) -> tuple[AreaRecord, ...]:
        """The Area and its ancestors out to the root, nearest first.

        One read of the Areas table rather than one per level: a query per ancestor would put a
        round trip on every preference read for every link of depth. A parent identifier naming
        no row of this tenant ends the walk there, which is the one silent reading in this module:
        the chain simply stops short of the missing row.

        The caller has confirmed the starting Area exists, so an empty answer means the walk was
        given an identifier it did not confirm.
        """
        areas = await self._areas.list_all()
        by_id = {area.id: area for area in areas}
        walked: list[AreaRecord] = []
        visited: set[AreaId] = set()
        current = by_id.get(area_id)
        while current is not None:
            if current.id in visited:
                raise UnreadableAreaAncestry(
                    f"the Areas' parent links form a cycle through "
                    f"{' -> '.join(area.name for area in walked)} -> {current.name}. No request "
                    "wrote this: an Area's place in the hierarchy is declared once against a "
                    "parent that exists and never moves, so this is stored data to repair"
                )
            if len(walked) >= MAX_AREA_DEPTH:
                raise UnreadableAreaAncestry(
                    f"the ancestry of {walked[0].name} runs past {MAX_AREA_DEPTH} Areas without "
                    "reaching a root. No request wrote this: an Area's place in the hierarchy is "
                    "declared once against a parent that exists and never moves, so this is "
                    "stored data to repair"
                )
            visited.add(current.id)
            walked.append(current)
            current = by_id.get(current.parent_id) if current.parent_id is not None else None
        return tuple(walked)

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
