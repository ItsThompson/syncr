"""Phase 5: the verdict a completed attempt is authoritative about.

**The derivation, in one sentence:** a solve's shortfalls are the probe's shortfalls plus one
packing failure synthesised from the blocked log for each deadline-bearing demand the attempt could
not place, because that is the only reading that preserves both the log's content and the promise
that the verdict panel and the backlog share one computation.

Every other reading loses something. Taking the probe's alone would drop the packing failure the
solve is the only component that can find, which is the transition ``US-FEAS-02`` requires and
``S8`` observes. Taking the synthesised ones alone would drop the three capacity shortfalls the
backlog's at-risk column reads, and the panel and the column would then disagree about one week.

## Why a solver verdict may claim what a probe verdict may not

Capacity arithmetic can prove a week impossible and cannot prove it possible: a week whose totals
are sufficient can still fail to pack, because the capacity exists in the wrong shape. A solve
ATTEMPTED the placement, so it knows the answer, and ``provenance = solver`` is what says the
reading is authoritative rather than a necessary condition.

## Only a deadline-bearing demand becomes a shortfall

A shortfall is a gap a tradeoff can be offered against, and the four kinds all name work that has
to fit before something. A due occurrence the week could not hold is charged by the ``staleness``
objective term instead, which is where "something is falling behind" belongs: a habit has no
deadline, so there is nothing for a gap to be measured against.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.feasibility import Provenance, Verdict, minimum_chunk_shortfall, probe
from syncr_solver.reading import demand_key

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.feasibility import Shortfall
    from syncr_solver.attempt import Attempt
    from syncr_solver.inputs import EligibleTask


def verdict_of(attempt: Attempt) -> Verdict:
    """Whether this week can hold its commitments, decided from the attempt that tried.

    The probe is run over the same assembly the solve read, through ``for_probe()``, so the two
    readings cannot have been computed against different inputs. Its own verdict carries the week's
    denominator, which is carried forward rather than re-derived from a second subtraction.
    """
    capacity = probe(attempt.inputs.for_probe())
    packing = _packing_failures(attempt)
    shortfalls = (*capacity.shortfalls, *packing)
    return Verdict(
        feasible=not shortfalls,
        provenance=Provenance.SOLVER,
        computed_at=attempt.inputs.now,
        input_version=attempt.inputs.input_version,
        discretionary_minutes=capacity.discretionary_minutes,
        shortfalls=shortfalls,
    )


def _packing_failures(attempt: Attempt) -> tuple[Shortfall, ...]:
    """One shortfall per deadline-bearing task the attempt left short, in the log's own order.

    The minutes are what is still unplaced rather than the whole demand, because a shortfall is the
    gap a tradeoff has to recover. The honored constraints name the task's own minimum chunk first,
    which is the declaration the user can act on, followed by what refused it: those come from the
    log rather than from a second pass over the rules, because the check that already knew is the
    one that recorded them.
    """
    placed = attempt.placed_minutes()
    refused = attempt.log.refused()
    found = []
    for task in _deadline_bearing(attempt.inputs.eligible_tasks):
        if task.binding not in refused:
            continue
        unplaced = task.remaining_minutes - placed.get(demand_key(task.binding), 0)
        if unplaced <= 0:
            continue
        found.append(
            minimum_chunk_shortfall(
                minutes=unplaced,
                chunk_minutes=task.min_chunk_minutes,
                against=(task.title,),
                blocked_by=attempt.log.honored_against(task.binding),
                deadline=task.deadline,
                area_id=task.area_id,
            )
        )
    return tuple(found)


def _deadline_bearing(tasks: Sequence[EligibleTask]) -> tuple[EligibleTask, ...]:
    """The tasks a shortfall can be measured against: the ones that owe work by an instant."""
    return tuple(task for task in tasks if task.deadline is not None)
