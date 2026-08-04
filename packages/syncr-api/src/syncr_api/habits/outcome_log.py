"""How this module acquires the outcome log the cursor and the debt are derived from.

The two derivations are pure functions of a habit and a sequence of outcomes, so what the
service needs is that sequence and nothing else. It is a protocol for the same reason the budget
report's occupancy reader is one: the concern that produces these rows owns its own storage, and
a habit response should acquire their answers rather than reach into another module's table.

``NoRecordedOutcomes`` answers with an empty log, and that is the correct reading of the schema
today rather than a placeholder for one. ``block_outcomes`` exists and carries a ``binding``
column, but the interior of a ``BindingRef`` is not defined anywhere yet: no code names the keys
a stored binding holds, and nothing writes one. So no row in this deployment can be attributed
to a habit occurrence, and the honest answer is that the log holds nothing for any habit: every
rotation habit reads as sitting on its first variant, and every habit owes nothing.

The seam earns its keep in the suite rather than in the production wiring. Without it, a cursor
and a debt figure could only ever be asserted against an empty log; with it, the service tests
supply a real one and assert both derivations through the service, with the real domain
functions throughout.

Whoever brings outcome recording online supplies a reader that reads ``block_outcomes`` and
changes one line in ``injection.py``. What that reader owes this module is the projection in
``syncr_domain.outcomes``: the habit the binding names, the occurrence key, the state, when the
occurrence was scheduled, and whether the day was confirmed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.identifiers import HabitId
    from syncr_domain.outcomes import HabitOutcome


class HabitOutcomeReader(Protocol):
    """What a habit response asks for the log its cursor and its debt are derived from."""

    async def read(self, habit_ids: Sequence[HabitId]) -> tuple[HabitOutcome, ...]:
        """Every recorded outcome whose binding names one of ``habit_ids``.

        One call for a list of habits rather than one per habit, so rendering a collection is a
        single read. The order is not part of the contract: both derivations are counts, and a
        count does not depend on the order it is taken in.
        """
        ...


class NoRecordedOutcomes:
    """The log of a deployment where no outcome can name a habit occurrence yet.

    Reads nothing and writes nothing. A habit rendered against it reads as never having had an
    occurrence recorded, which is what is true while nothing writes a binding.
    """

    async def read(self, habit_ids: Sequence[HabitId]) -> tuple[HabitOutcome, ...]:
        return ()
