"""Where a concrete entry's binding is confirmed to name a row this tenant holds.

Two tables answer for a concrete entry's binding and they have no shared parent, so the
``binding_target`` says which to read and this module turns that into the read itself: ONE
mapping here keyed by :class:`BindingTarget` member rather than a branch in the service and
again on every route, in the style ``preferences/owners.py`` already sets. A third target is an
entry in the mapping, and the suite asserts the mapping covers the vocabulary, so adding one
without a reader fails a test rather than resolving against whichever table a reader looked in
first.

The reads are the repositories' own tenant-scoped ``find``, so another tenant's row answers as
absent and one refusal sentence covers both: a request naming an identifier nobody holds and one
naming another tenant's row are answered identically, and the response discloses nothing about
which. The keying on the target is also what keeps an entry whose target names one table from
resolving against the other table's identifier, in either direction: a habit's identifier read
through the routines' reader finds no routine, whatever that identifier names elsewhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.templates import BindingTarget

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from syncr_api.habits.repository import HabitRepository
    from syncr_api.routines.repository import RoutineRepository


class TemplateBindings:
    """Reads whether a concrete entry's binding names a row this tenant holds."""

    def __init__(self, routines: RoutineRepository, habits: HabitRepository) -> None:
        self._readers: dict[BindingTarget, Callable[[UUID], Awaitable[bool]]]
        self._readers = {
            BindingTarget.ROUTINE: self._a_routine,
            BindingTarget.HABIT: self._a_habit,
        }
        self._routines = routines
        self._habits = habits

    @property
    def targets(self) -> frozenset[BindingTarget]:
        """The targets this lookup can read. Asserted against the vocabulary itself."""
        return frozenset(self._readers)

    async def holds(self, target: BindingTarget, ref: UUID) -> bool:
        """Whether this tenant holds the row this target and identifier name."""
        return await self._readers[target](ref)

    async def _a_routine(self, ref: UUID) -> bool:
        return await self._routines.find(ref) is not None

    async def _a_habit(self, ref: UUID) -> bool:
        return await self._habits.find(ref) is not None
