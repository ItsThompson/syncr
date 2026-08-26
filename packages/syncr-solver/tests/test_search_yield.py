"""What each move kind buys a bounded descent, and the iteration the last acceptance lands on.

``Improved`` carries the iterations and the acceptances in total. Which KIND produced each
acceptance, and where inside the budget the last one fell, are the two figures the choice between
bounding the search's tail and re-ordering its kinds rests on, and nothing in the package publishes
either. :mod:`tests.search_yield` measures them by running the descent with a counter per kind, and
this file is what says that instrument is the shipped loop rather than a second one:

- the descent it runs reaches the same iterations, the same acceptances and the same total as
  :func:`~syncr_solver.search.improve`, on the pass that exhausts the generator and on the pass the
  budget cuts short;
- each kind holds its own column, so a profile keyed to the wrong kind is not a profile with the
  right sum;
- the iteration of the last acceptance is crossed against ``improve`` alone, at three budgets, so it
  is pinned by something other than the instrument that reported it.

**Every figure below is the week's rather than the machine's**, which is why they are counts and
totals and never seconds: the per-kind wall time is reported by ``python -m tests.measure_solve
yield`` and asserted nowhere, because an assertion over it would measure the host. The counts move
when the objective, the generator or a fixture week moves, so re-measure with that command rather
than adjusting a figure to match.
"""

from __future__ import annotations

import pytest

from syncr_solver.budget import SolveBudget, never_cancelled
from syncr_solver.moves import RELOCATE, RESIZE, RESPLIT, SWAP
from syncr_solver.search import improve
from tests.measure_solve import a_dense_week, a_saturated_week
from tests.objective_weeks import hand_tuned_weights
from tests.reference_week import reference_week
from tests.search_yield import Acceptance, Yield, constructed, descend

SHIPPED = SolveBudget()

# The reference week's descent, measured through `python -m tests.measure_solve yield` and
# reproduced by the cases below. The budget's 200 rather than the descent's own end, because this
# week now reaches its optimum past the budget: the generator is cut short with the plan already
# at the total a longer budget confirms it keeps.
A_REFERENCE_PROFILE = (
    pytest.param(RELOCATE, 125, 6, id="relocate"),
    pytest.param(SWAP, 45, 0, id="swap"),
    pytest.param(RESIZE, 26, 0, id="resize"),
    pytest.param(RESPLIT, 4, 2, id="re_split"),
)

# The reference week's last acceptance. A budget of this many moves stops the search on the move it
# would accept, one more buys it, and the whole budget buys nothing further.
LAST_ACCEPTANCE = 175
ACCEPTANCES = 8


@pytest.fixture(scope="module")
def descended() -> Yield:
    """One descent over the reference week at the shipped budget, for the whole module.

    Once rather than per case: the figures are deterministic, so a second run of the same week under
    the same budget is the same reading at the price of another two hundred objective evaluations.
    """
    weights = hand_tuned_weights()
    return descend(constructed(reference_week(), weights, budget=SHIPPED), weights, budget=SHIPPED)


def improved_at(moves: int) -> tuple[int, float]:
    """What the shipped loop accepts and what it costs, given a budget of ``moves``.

    The construction is the same three phases at the same budget every time, so the two figures
    differ between calls only by what the descent itself did with them.
    """
    weights = hand_tuned_weights()
    budget = SolveBudget(move_evaluations=moves)
    found = improve(
        constructed(reference_week(), weights, budget=budget),
        weights,
        budget=budget,
        cancelled=never_cancelled,
    )
    return found.accepted, found.breakdown.total()


# --------------------------------------------------------------------------------------
# The instrument is the loop
# --------------------------------------------------------------------------------------


def test_the_instrument_runs_the_descent_the_shipped_loop_runs() -> None:
    """The same three figures, reached twice: once by ``improve`` and once by the instrument.

    This is the whole licence for reading a per-kind column off the instrument. The two agree on the
    iterations, on the acceptances and on the objective total, and the total is the one that would
    separate two loops that spent the same budget on different moves.
    """
    weights = hand_tuned_weights()
    attempt = constructed(reference_week(), weights, budget=SHIPPED)
    shipped = improve(attempt, weights, budget=SHIPPED, cancelled=never_cancelled)
    measured = descend(attempt, weights, budget=SHIPPED)

    assert (measured.iterations, measured.accepted) == (shipped.iterations, shipped.accepted)
    assert measured.total == shipped.breakdown.total()
    # The control on the arm above: a descent that agreed on nothing but zero would satisfy it.
    assert measured.accepted == ACCEPTANCES
    # The budget is what stops this descent now: the week's optimum sits past its 200th move, so
    # the shipped exit is the cut-short one and the exhausted-pass case is the test below.
    assert measured.iterations == SHIPPED.move_evaluations


def test_the_instrument_runs_the_descent_the_budget_cuts_short() -> None:
    """The other exit: the budget is spent mid-pass, so the last move counted is never evaluated.

    ``improve`` counts a move as an iteration and then returns without scoring it, which is a figure
    the exhausted pass above cannot see. Fifty moves rather than the shipped two hundred, because
    this week's optimum sits past 200 and a budget above that never takes this exit.
    """
    weights = hand_tuned_weights()
    budget = SolveBudget(move_evaluations=50)
    attempt = constructed(reference_week(), weights, budget=budget)
    shipped = improve(attempt, weights, budget=budget, cancelled=never_cancelled)
    measured = descend(attempt, weights, budget=budget)

    assert (measured.iterations, measured.accepted) == (shipped.iterations, shipped.accepted)
    assert measured.total == shipped.breakdown.total()
    assert measured.iterations == budget.move_evaluations
    # Four of the nine the whole budget buys, so this case is a shortened descent rather than the
    # same one under another name.
    assert measured.accepted == 4


def test_the_instrument_runs_the_descent_the_rejection_bound_cuts_short() -> None:
    """The third exit: a run of refusals fires mid-pass, and the counted move is never evaluated.

    A run of thirty is longer than any stretch this week's early acceptances sit behind but shorter
    than the one its last acceptance needs, so the bound ends a descent the move budget would have
    carried further. The tail is the run plus the one move counted past it, the same shape the
    budget's own exit reports.
    """
    weights = hand_tuned_weights()
    budget = SolveBudget(rejection_run=30, checkpoint_every=10_000)
    attempt = constructed(reference_week(), weights, budget=budget)
    shipped = improve(attempt, weights, budget=budget, cancelled=never_cancelled)
    measured = descend(attempt, weights, budget=budget)

    assert (measured.iterations, measured.accepted) == (shipped.iterations, shipped.accepted)
    assert measured.total == shipped.breakdown.total()
    assert measured.iterations < SHIPPED.move_evaluations
    assert measured.tail == budget.rejection_run + 1


# --------------------------------------------------------------------------------------
# Each kind's own column
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("kind", "considered", "accepted"), A_REFERENCE_PROFILE)
def test_each_move_kind_holds_the_column_the_reference_week_gives_it(
    descended: Yield, kind: str, considered: int, accepted: int
) -> None:
    """One kind, its own moves offered and its own moves taken, keyed by the generator's name.

    Four cases rather than one over the sums, because a profile that attributed every kind's work to
    one column would sum to the same 200 iterations and the same 8 acceptances. Every count here is
    distinct from every other, so a column read under the wrong name is red rather than plausible.

    Resize offers twenty-six moves and the objective takes none of them. That is the measured zero
    this week has, and it is asserted rather than skipped: a kind that stopped being offered at all
    would otherwise read the same as a kind the objective refused.
    """
    column = descended.of_kind(kind)

    assert (column.considered, column.accepted) == (considered, accepted)


def test_the_kinds_columns_account_for_every_iteration_and_every_acceptance(
    descended: Yield,
) -> None:
    """The four columns are a partition, and the acceptances arrived in one order.

    The per-kind cases above each hold one column, and all four holding their own figure would still
    admit a fifth move nobody counted: the sums cross the columns against the totals ``improve``
    also reports, which is what makes the split a split.

    The order is the third reading and the counts cannot see it. Eight acceptances of these three
    kinds in any other sequence satisfy both sums, and the sequence is what says which kind was
    buying improvements late in the descent rather than early.
    """
    assert sum(column.considered for column in descended.kinds) == descended.iterations
    assert sum(column.accepted for column in descended.kinds) == descended.accepted
    assert [taken.kind for taken in descended.acceptances] == [
        RELOCATE,
        RELOCATE,
        RELOCATE,
        RELOCATE,
        RESPLIT,
        RELOCATE,
        RELOCATE,
        RESPLIT,
    ]


# --------------------------------------------------------------------------------------
# The iteration of the last acceptance
# --------------------------------------------------------------------------------------


def test_the_last_acceptance_is_the_iteration_the_final_total_needs() -> None:
    """The instrument's 135 crossed against ``improve`` alone, at three budgets.

    A budget of 135 stops on the move that would be accepted, because a move is counted and then
    refused the evaluation. 136 buys it: one more acceptance and a strictly lower total. The whole
    budget buys nothing further, which is what makes 135 the LAST acceptance rather than merely an
    acceptance. Nothing here reads the instrument, so the figure it reported is pinned by a second
    reading rather than by itself.
    """
    before, costing_more = improved_at(LAST_ACCEPTANCE)
    after, costing_less = improved_at(LAST_ACCEPTANCE + 1)
    whole, final = improved_at(SHIPPED.move_evaluations)

    assert (before, after) == (ACCEPTANCES - 1, ACCEPTANCES)
    assert costing_less < costing_more
    assert (whole, final) == (ACCEPTANCES, costing_less)


def test_the_last_acceptance_the_instrument_reports_is_that_iteration(descended: Yield) -> None:
    """The instrument's own reading of the crossing above, which is the figure the mode prints."""
    assert descended.last_acceptance == LAST_ACCEPTANCE
    assert descended.tail == 25


# --------------------------------------------------------------------------------------
# The two large weeks: where the budget goes
# --------------------------------------------------------------------------------------


def test_the_dense_weeks_whole_budget_is_spent_inside_the_first_kind() -> None:
    """The budget is exhausted among relocations, so the other three kinds are never reached.

    The week the budget's own two numbers were sized against, which still leaves 330 minutes in no
    block. The generator offers relocations first and a 225-block week with slack has more of them
    than the budget can consider, so demoting a later kind cannot recover time it never spent.

    Four acceptances, the last at 178 of 200. **A week that accepted none would be red here**, and a
    descent that accepted on every pass would be too: both are figures about the week rather than
    about the loop, so they are stated as the counts this week gives.
    """
    weights = hand_tuned_weights()
    found = descend(constructed(a_dense_week(), weights, budget=SHIPPED), weights, budget=SHIPPED)

    assert found.of_kind(RELOCATE).considered == SHIPPED.move_evaluations
    assert [column.considered for column in found.kinds if column.kind != RELOCATE] == [0, 0, 0]
    assert (found.accepted, found.last_acceptance) == (4, 178)
    assert found.tail == 22


def test_a_week_with_nothing_unallocated_offers_no_relocation_at_all() -> None:
    """With no gap left, the first kind offers nothing and the second stops on the rejection bound.

    A relocation needs a gap that can hold the block, and this week has no gap at all: that is what
    ``unallocated 0`` means, and it is why the kind that dominates the other weeks is empty here.
    The swaps accept once, at 39, and the bound then ends the descent one move past the run it
    tolerates: the 121 iterations after the acceptance are all the proof of nothing improving this
    week buys, where the move budget alone would have bought 161.

    The empty gap tuple is the precondition rather than a second assertion of the same thing: a week
    that stopped being saturated would offer relocations again, and the columns below would be a
    reading of a different week under the same name.

    **That acceptance's iteration is then crossed through ``improve`` alone**, at the two budgets on
    either side of it, because the tail this week reports is the figure a stop condition would be
    sized against and the instrument must not be its only witness. The crossing shares this case's
    construction: on a week this size that is the expensive half, and a case of its own would pay it
    again to state one more figure.
    """
    weights = hand_tuned_weights()
    attempt = constructed(a_saturated_week(), weights, budget=SHIPPED)
    found = descend(attempt, weights, budget=SHIPPED)
    before = improve(
        attempt, weights, budget=SolveBudget(move_evaluations=39), cancelled=never_cancelled
    )
    after = improve(
        attempt, weights, budget=SolveBudget(move_evaluations=40), cancelled=never_cancelled
    )

    assert attempt.gaps() == ()
    assert found.of_kind(RELOCATE).considered == 0
    assert found.of_kind(SWAP).considered == 39 + SHIPPED.rejection_run + 1
    assert found.iterations == found.of_kind(SWAP).considered
    assert (found.accepted, found.last_acceptance, found.tail) == (
        1,
        39,
        SHIPPED.rejection_run + 1,
    )
    assert [taken.kind for taken in found.acceptances] == [SWAP]
    # The same iteration, reached without the instrument: 39 stops on the move it would accept and
    # 40 buys it, for a strictly cheaper plan.
    assert (before.accepted, after.accepted) == (0, 1)
    assert after.breakdown.total() < before.breakdown.total()


# --------------------------------------------------------------------------------------
# The readings a rejection-stop threshold would be chosen against
# --------------------------------------------------------------------------------------

A_DESCENT = (
    # Nothing accepted: every iteration is tail, and there is no acceptance a rejection stop could
    # cost, so the run it would have to exceed is zero.
    pytest.param((), 200, 200, 0, id="nothing-accepted"),
    # One acceptance on the first move: no tail before it and no rejection behind it.
    pytest.param((1,), 12, 11, 0, id="accepted-on-the-first-move"),
    # Two acceptances: 2 rejections behind the first and 6 behind the second, and 2 after the last.
    pytest.param((3, 10), 12, 2, 6, id="two-acceptances"),
    # The longest run is not the last one: a stop above 6 would keep both acceptances.
    pytest.param((10, 12), 12, 0, 9, id="the-longest-run-comes-first"),
)


@pytest.mark.parametrize(("at", "iterations", "tail", "longest"), A_DESCENT)
def test_the_tail_and_the_longest_rejection_run_are_read_off_the_acceptances(
    at: tuple[int, ...], iterations: int, tail: int, longest: int
) -> None:
    """The two readings a rejection-stop threshold would be chosen against, over literal descents.

    The tail is what such a stop could recover and the longest run is what it would have to exceed
    to cost no acceptance the search makes today. Both are arithmetic over the acceptance indices,
    so they are driven from literals here rather than from a week: a fixture cannot state the
    boundary cases, and an off-by-one in either would move the threshold the figures argue for.
    """
    found = Yield(
        kinds=(),
        acceptances=tuple(Acceptance(iteration=index, kind=RELOCATE, total=1.0) for index in at),
        iterations=iterations,
        total=1.0,
        seconds=0.0,
        drained_seconds=0.0,
    )

    assert (found.tail, found.longest_run_before_an_acceptance) == (tail, longest)
