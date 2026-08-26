"""The per-kind yield of one bounded descent: what each move kind offered, cost and bought.

:func:`~syncr_solver.search.improve` answers with the plan, its cost, the iterations it spent and
the acceptances it made. It does not say which KIND of move each acceptance was, nor which iteration
the last one landed on, and neither does anything else in the package: a caller that wants those
figures has to watch the loop rather than read its result.

So this module runs the descent itself, over the same generator and the same objective, with three
counters around each move. It is an instrument rather than a second implementation, and the
difference is asserted rather than asserted-to: ``tests/test_search_yield.py`` crosses
:func:`descend` against ``improve`` on two weeks and requires the same iterations, the same
acceptances and the same total, so a mirror that has drifted from the loop is a red suite rather
than a wrong measurement.

Two properties of the real loop are deliberately narrowed here, and both are declared because they
bound what the figures mean.

``cancelled`` is not mirrored. ``improve`` asks a predicate every ``checkpoint_every`` iterations
and returns the plan it had; this descent never asks, so it measures the whole budget. A measurement
of what a cancelled solve does would be a measurement of when the caller cancelled.

The wall time per kind is the time to GENERATE the move plus the time to evaluate it, which is the
cost of offering that kind at all. The generator's final, empty step belongs to no kind and is
carried separately, so the four columns sum to less than the descent's own elapsed time rather than
silently absorbing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING

from syncr_solver.attempt import Attempt
from syncr_solver.binding import bind_slots
from syncr_solver.filling import fill_gaps
from syncr_solver.inheritance import inherited
from syncr_solver.materialize import derive
from syncr_solver.metrics import MaterializeCause
from syncr_solver.moves import RELOCATE, RESIZE, RESPLIT, SWAP, moves
from syncr_solver.objective import evaluate
from syncr_solver.preferred import ResolvedPreferences

if TYPE_CHECKING:
    from syncr_solver.budget import SolveBudget
    from syncr_solver.inputs import SolveInputs
    from syncr_solver.weights import WeightSet

KINDS: tuple[str, ...] = (RELOCATE, SWAP, RESIZE, RESPLIT)
"""The four kinds in the order the generator offers them, from the generator's own constants."""


@dataclass(frozen=True, slots=True, kw_only=True)
class KindYield:
    """What one move kind offered a descent, what it cost, and what the objective took."""

    kind: str
    considered: int
    accepted: int
    seconds: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Acceptance:
    """One accepted move: the iteration it landed on, its kind, and the total it left behind."""

    iteration: int
    kind: str
    total: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Yield:
    """One descent, per kind and in whole, plus where the acceptances fell inside it."""

    kinds: tuple[KindYield, ...]
    acceptances: tuple[Acceptance, ...]
    iterations: int
    total: float
    seconds: float
    drained_seconds: float

    @property
    def accepted(self) -> int:
        """How many moves the objective took, which is ``Improved.accepted``'s figure."""
        return len(self.acceptances)

    @property
    def last_acceptance(self) -> int | None:
        """The iteration the last accepted move landed on, or nothing because none did."""
        return self.acceptances[-1].iteration if self.acceptances else None

    @property
    def tail(self) -> int:
        """The iterations spent after the last acceptance, which is all of them where none was."""
        last = self.last_acceptance
        return self.iterations if last is None else self.iterations - last

    @property
    def longest_run_before_an_acceptance(self) -> int:
        """The most consecutive rejections any acceptance here sits behind.

        What a consecutive-rejection stop would have to exceed to leave this descent's acceptances
        reachable: a threshold at or below this figure stops the search before the acceptance that
        run precedes. Zero where nothing was accepted, because there is then no acceptance to lose.
        """
        runs = []
        previous = 0
        for taken in self.acceptances:
            runs.append(taken.iteration - previous - 1)
            previous = taken.iteration
        return max(runs, default=0)

    def of_kind(self, kind: str) -> KindYield:
        """This kind's column, by name rather than by position."""
        return next(column for column in self.kinds if column.kind == kind)


def constructed(week: SolveInputs, weights: WeightSet, *, budget: SolveBudget) -> Attempt:
    """The plan the first three phases produce, which is what the descent starts from.

    The same three steps ``solve`` takes before it calls ``improve``: what derivation determines and
    what the week inherits, then the content into the slots the template fixed, then the cadence and
    the task work into what is left. Starting from an empty attempt instead would measure a descent
    over a plan the entry point never produces.
    """
    attempt = Attempt.of(
        week,
        placements=inherited(week, derive(week, cause=MaterializeCause.PHASE1).document.blocks),
    )
    return fill_gaps(bind_slots(attempt), weights, budget=budget)


def descend(attempt: Attempt, weights: WeightSet, *, budget: SolveBudget) -> Yield:
    """The descent ``improve`` runs over this plan, with the yield of each kind recorded.

    The loop is the loop: first improvement, strict inequality, restart the pass on an acceptance,
    stop on the budget or on a run of rejections, and an iteration per move CONSIDERED whether a
    rule refused it or the objective did. The counters are the only addition, and the module
    docstring names the one narrowing.
    """
    preferences = ResolvedPreferences(attempt.inputs.preferences)
    current = attempt
    total = evaluate(current.document(), inputs=current.inputs, weights=weights).total()
    tally = _Tally()
    started = perf_counter()
    iterations = 0
    rejections = 0
    improving = True
    while improving and iterations < budget.move_evaluations:
        improving = False
        offered = moves(current, preferences)
        while True:
            at = perf_counter()
            move = next(offered, None)
            generating = perf_counter() - at
            if move is None:
                tally.drained(generating)
                break
            iterations += 1
            if iterations >= budget.move_evaluations or rejections >= budget.rejection_run:
                tally.considered(move.kind, generating)
                return tally.reading(
                    iterations=iterations, total=total, seconds=perf_counter() - started
                )
            at = perf_counter()
            found = evaluate(move.attempt.document(), inputs=current.inputs, weights=weights)
            tally.considered(move.kind, generating + perf_counter() - at)
            if found.total() >= total:
                rejections += 1
                continue
            current, total = move.attempt, found.total()
            rejections = 0
            tally.accepted(iteration=iterations, kind=move.kind, total=total)
            improving = True
            break
    return tally.reading(iterations=iterations, total=total, seconds=perf_counter() - started)


class _Tally:
    """The three counters a descent fills, kept off the loop so the loop stays the loop."""

    def __init__(self) -> None:
        self._considered = dict.fromkeys(KINDS, 0)
        self._seconds = dict.fromkeys(KINDS, 0.0)
        self._accepted: list[Acceptance] = []
        self._drained = 0.0

    def considered(self, kind: str, seconds: float) -> None:
        self._considered[kind] += 1
        self._seconds[kind] += seconds

    def accepted(self, *, iteration: int, kind: str, total: float) -> None:
        self._accepted.append(Acceptance(iteration=iteration, kind=kind, total=total))

    def drained(self, seconds: float) -> None:
        self._drained += seconds

    def reading(self, *, iterations: int, total: float, seconds: float) -> Yield:
        return Yield(
            kinds=tuple(
                KindYield(
                    kind=kind,
                    considered=self._considered[kind],
                    accepted=sum(1 for taken in self._accepted if taken.kind == kind),
                    seconds=self._seconds[kind],
                )
                for kind in KINDS
            ),
            acceptances=tuple(self._accepted),
            iterations=iterations,
            total=total,
            seconds=seconds,
            drained_seconds=self._drained,
        )
