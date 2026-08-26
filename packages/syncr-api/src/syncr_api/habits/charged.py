"""The stored charge on a habit row, and the one thing that ever writes it.

``charged_misses`` is the walked count of confirmed misses less the make-ups completed against
them, floored per credit: :func:`syncr_domain.debt.charged_misses` over the rows the log holds
for that habit. It is stored so a reader that cannot afford the log's whole history still answers
with the figure the log supports, and it is exact wherever the log is because it is the same walk,
run inside the transaction that changed the rows.

**The outcome write is the only writer.** Every mutation of ``block_outcomes`` goes through the
outcome service, so restating the affected habits' counts there covers recording, confirming,
backfilling, correcting, and the drills, which drive the same routes. A route or an edit that set
the count by hand would be a second answer to what the log charges, and none exists.

**Lock before reading the log.** The maintainer takes the habit rows' locks first, via
``HabitRepository.hold``, so two transactions confirming days for one habit serialize their walks
instead of each committing a count computed over a log that lacked the other's rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from syncr_api.habits.rules import stated_rejection
from syncr_domain.debt import charged_misses
from syncr_domain.identity import BindingKind

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.core.clock import Clock
    from syncr_api.habits.outcome_log import HabitOutcomeReader
    from syncr_api.habits.repository import HabitRepository
    from syncr_domain.identifiers import HabitId
    from syncr_domain.identity import BindingRef


class ChargedMissesMaintainer(Protocol):
    """What an outcome write asks for after it changes the log."""

    async def refresh(self, habit_ids: Sequence[HabitId]) -> None:
        """Restate these habits' walked charges from the log as it now stands."""
        ...


class StoredChargedMisses:
    """Restates the stored charge from the log, for the habits an outcome write touched."""

    def __init__(self, habits: HabitRepository, outcomes: HabitOutcomeReader, clock: Clock) -> None:
        self._habits = habits
        self._outcomes = outcomes
        self._clock = clock

    async def refresh(self, habit_ids: Sequence[HabitId]) -> None:
        """Walk each named habit's rows and write the count when it moved.

        One read of the log for the whole collection, keyed to the habits actually locked, because
        a confirmation settles many blocks and several habits at once. A count that already matches
        is not written: the common case is a presumption landing unconfirmed, which charges nothing.
        """
        unique = sorted(set(habit_ids))
        if not unique:
            return
        records = await self._habits.hold(unique)
        if not records:
            return
        log = await self._outcomes.read([record.id for record in records])
        now = self._clock()
        for record in records:
            with stated_rejection():
                habit = record.as_habit()
            charged = charged_misses(habit, log, now)
            if charged != record.charged_misses:
                await self._habits.write_charged_misses(record.id, charged=charged)


def habit_ids_of(binding: BindingRef) -> tuple[HabitId, ...]:
    """The habit a block's binding names, or nothing: routines and tasks charge no habit."""
    return (binding.entity_id,) if binding.kind is BindingKind.HABIT else ()
