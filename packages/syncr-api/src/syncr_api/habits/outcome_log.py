"""How this module acquires the outcome log the cursor and the debt are derived from.

The two derivations are pure functions of a habit and a sequence of outcomes, so what the
service needs is that sequence and nothing else. It is a protocol for the same reason the budget
report's occupancy reader is one: the concern that produces these rows owns its own storage, and
a habit response should acquire their answers rather than reach into another module's table.

``NoRecordedOutcomes`` answers with an empty log. It is kept for the ONE suite that still needs it:
``tests/test_habits_service.py`` asserts that a habit with no recorded outcome reads as sitting on
its first variant and owing nothing, and a fake that answers with nothing is the honest way to state
that. Production wires :class:`syncr_api.plans.habit_log.HabitOutcomeLog`, which reads the log for
real.

The seam earns its keep in the suite as well as in the wiring. The service tests supply a real log
and assert both derivations through the service, with the real domain functions throughout, without
reaching a database.

What a reader owes this module is the projection in ``syncr_domain.outcomes``: the habit the binding
names, the occurrence key, the state, when the occurrence was scheduled, and whether the day was
confirmed.
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

        **At most one row per ``(habit_id, occurrence_key)``.** Both derivations are counts over the
        rows they are given, so a second row for one occurrence is counted twice: two completions of
        occurrence ``"00"`` put the cursor one variant ahead, and one miss delivered three times is
        charged three times until the cap clamps it. Neither derivation can defend the invariant,
        because a count cannot tell a duplicate from a second occurrence. That is what
        ``HabitOutcome.occurrence_key`` is carried for: it is read by neither derivation and it is
        the thing this precondition is stated over.

        The invariant is held by the WRITE path rather than by a rule here. ``block_outcomes`` is
        keyed by ``(tenant_id, block_id)``, and a block id is a digest of the week and the binding,
        so one habit occurrence in one week is one block and one block is one row. The schema first
        shipped keyed by ``(block_id, revision_id)``, which permitted a row per plan of record and
        would have delivered exactly the shape above; that identity was narrowed rather than a
        latest-revision rule being invented here, because a revision boundary is not something the
        user can see.

        Every instant a row carries has to be a real instant. ``HabitOutcome`` normalizes through
        ``syncr_domain.intervals.as_instant`` on construction and refuses a naive datetime, so a
        reader composing rows from a driver that hands back naive values learns it here rather than
        as a comparison against a wall clock two layers down.

        One call for a list of habits rather than one per habit, so rendering a collection is a
        single read. The order is not part of the contract: both derivations are counts, and a
        count does not depend on the order it is taken in.
        """
        ...


class NoRecordedOutcomes:
    """An empty log, for the suite that asserts what a habit with no recorded outcome reads as.

    Reads nothing and writes nothing. A habit rendered against it reads as never having had an
    occurrence recorded, which is the state every habit starts in.

    Kept rather than deleted because ``tests/test_habits_service.py`` states that reading with it,
    and a service test that had to seed an empty table to say "nothing has been recorded" would be
    asserting the seeding. Production wires
    :class:`syncr_api.plans.habit_log.HabitOutcomeLog`.
    """

    async def read(self, habit_ids: Sequence[HabitId]) -> tuple[HabitOutcome, ...]:
        return ()
