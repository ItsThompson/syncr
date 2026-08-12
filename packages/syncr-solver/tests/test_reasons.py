"""The reason record: what each clause is drawn from, and what a block may say about itself.

Every assertion here is about a PROJECTION. The solve has already decided; ``assemble`` reads the
refusals, the breakdown, the pins and the Area figures and turns them into rows a panel renders. So
the tests are shaped around the two questions that matter for a projection:

**Does the clause appear where it should, and stay away where it should not?** Every kind is driven
from a state that must produce it and from a state that must not, because a clause that is always
emitted explains nothing and a guard that never fires is not a guard.

**Does every value trace to something the solve computed?** :func:`untraceable` is the instrument
for that, and it is shown to reject a fabricated clause before it is used to accept a real record.
A sentence that cannot be traced to a value the solver computed is worse than no sentence, and no
language model is in this path at all: the values are the log's, the breakdown's, the pins' and the
Area figures', and the parameter list is what makes that decidable.

The reference week's own records are asserted beside the golden file, in ``test_reference_week``,
because the budget over a real week is a claim about that fixture rather than about these builders.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import TYPE_CHECKING, Final, get_args
from uuid import UUID

import pytest

from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingRef
from syncr_domain.reasons import (
    CLAUSE_BUDGET,
    MAX_CLAUSES,
    Blocked,
    Bound,
    Clause,
    DerivationSource,
    Dominant,
    Floor,
    InsteadOf,
    Pinned,
)
from syncr_solver.attempt import ROWS_PER_BINDING
from syncr_solver.constraints import Blocked as Rejection
from syncr_solver.constraints import BlockedCandidate, ConstraintRule
from syncr_solver.materialize import materialize
from syncr_solver.metrics import MaterializeCause
from syncr_solver.reasons import BLOCKED_PER_BLOCK, CHURN, assemble, explained
from syncr_solver.state import PartialPlan
from syncr_solver.terms import StalenessInput
from syncr_solver.weights import OBJECTIVE_TERMS
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    a_block,
    a_concrete_entry,
    a_frame_entry,
    a_live_plan,
    a_pin,
    a_prep_block,
    a_slot,
    an_anchor,
    an_area_budget,
    between,
    on,
)
from tests.objective_weeks import (
    A_MOMENT,
    A_REVISION,
    a_breakdown,
    an_eligible_task,
    an_occurrence,
)
from tests.preference_yield_week import (
    COMMITMENT,
    EARLY,
    MIDDAY,
    PLACED_AT,
    VARIANT,
    preference_yield_week,
)
from tests.solve_weeks import a_week, solved

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_domain.identifiers import AreaId
    from syncr_domain.plan import Block, PlanDocument
    from syncr_domain.reasons import ReasonRecord
    from syncr_solver.inputs import AreaBudget, Pin, SolveInputs
    from syncr_solver.objective import ObjectiveBreakdown
    from syncr_solver.solve import SolveResult

A_HABIT: Final = UUID("00000000-0000-4000-8000-0000000000d1")
THE_OTHER_HABIT: Final = UUID("00000000-0000-4000-8000-0000000000d2")
A_TASK_OF_ITS_OWN: Final = UUID("00000000-0000-4000-8000-0000000000d3")

# A Fitness floor and the figures around it, so the three the clause renders are distinguishable
# from each other: a declared five hours, an hour of it held by a placement the solver may not
# move, and two hours held in all.
DECLARED_FLOOR: Final = 300
IMMOVABLE_MINUTES: Final = 60
PLACED_MINUTES: Final = 120


def a_floored_area(
    *,
    area_id: AreaId = FITNESS,
    name: str = "Fitness",
    floor_minutes: int = DECLARED_FLOOR - IMMOVABLE_MINUTES,
    target_minutes: int = 0,
    max_per_day_minutes: int | None = None,
) -> AreaBudget:
    """One Area whose floor is partly served, with the two floor quantities genuinely different.

    ``floor_minutes`` nets the immovable placements and the reservation nets every placement, so a
    week holding both kinds is the only one where a reader can tell the two figures apart.
    """
    return an_area_budget(
        area_id=area_id,
        name=name,
        floor_minutes=floor_minutes,
        floor_reservation_minutes=DECLARED_FLOOR - PLACED_MINUTES,
        placed_minutes=PLACED_MINUTES,
        target_minutes=target_minutes,
        max_per_day_minutes=max_per_day_minutes,
    )


def records_of(
    plan: PlanDocument,
    *,
    breakdown: ObjectiveBreakdown | None = None,
    pins: Sequence[Pin] = (),
    areas: Sequence[AreaBudget] = (),
    log: Sequence[BlockedCandidate] = (),
) -> tuple[ReasonRecord, ...]:
    """``assemble`` over one plan, with everything a test does not drive left empty."""
    return assemble(plan, blocked_log=log, breakdown=breakdown, pins=pins, areas=areas)


def kinds_in(record: ReasonRecord) -> tuple[str, ...]:
    return tuple(type(clause).__name__ for clause in record.clauses)


def inputs_named_in(record: ReasonRecord) -> tuple[str, ...]:
    """Which of the staleness inputs' spellings this record's clauses carry as a value.

    Over the whole record rather than one clause, because what a block can say is the whole record.
    The spellings come from :class:`~syncr_solver.terms.StalenessInput` rather than being written
    out here, so the reading is keyed to the vocabulary it covers.

    Values rather than field names, and by equality rather than by substring, so a field NAMED for
    an input does not read as a clause carrying one. ``bound`` is where that matters in the other
    direction: ``BindingSource.ROTATION`` is a habit's own vocabulary and a block whose content came
    from a rotation cursor carries it truthfully, which this reading finds and a test below states.
    """
    spellings = {member.value for member in StalenessInput}
    carried = {value for clause in record.clauses for value in _values(clause)}
    return tuple(sorted(carried & spellings))


def _values(value: object) -> Iterator[str]:
    """Every field value of ``value`` as text, reaching into any dataclass it holds."""
    if is_dataclass(value) and not isinstance(value, type):
        for held in fields(value):
            yield from _values(getattr(value, held.name))
        return
    yield str(value)


def clauses_of(result: SolveResult, title: str) -> tuple[Clause, ...]:
    """Every clause the one block with this title carries, from a solved week."""
    block = next(block for block in result.document.blocks if block.title == title)
    return block.reason.clauses


def only(kind: type, clauses: Sequence[Clause]) -> Clause:
    """The one clause of this kind among these, so a test names what it is asserting about."""
    found = [clause for clause in clauses if isinstance(clause, kind)]
    assert len(found) == 1, f"{kind.__name__}: {found}"
    return found[0]


def a_solved_week(**overrides: object) -> SolveResult:
    """One week with content the solver chooses, solved through the real entry point.

    The Area's target is well above the minutes the week places in it, so the plan costs something
    and a ``dominant`` clause has a term to name. A week whose every term is zero is its own test.
    """
    stated: dict[str, object] = {
        "habit_occurrences": (
            an_occurrence(habit_id=A_HABIT, index=0, minutes=60, area_id=FITNESS, title="Walk"),
        ),
        "areas": (an_area_budget(area_id=FITNESS, target_minutes=300),),
    }
    stated.update(overrides)
    return solved(a_week(**stated))


# --------------------------------------------------------------------------------------
# The instrument: every value a clause carries came from one of the four sources
# --------------------------------------------------------------------------------------


def untraceable(
    block: Block,
    *,
    log: Sequence[BlockedCandidate] = (),
    breakdown: ObjectiveBreakdown | None = None,
    pins: Sequence[Pin] = (),
    areas: Sequence[AreaBudget] = (),
) -> list[str]:
    """Which of this block's clauses carry a value none of the sources holds.

    Membership rather than a second derivation: each clause's own fields are looked for among the
    values the solve computed, so a value assembled out of nothing fails and a value merely
    RE-ARRANGED does not pass by accident. The floor's ``of`` is the one figure that is arithmetic
    over two carried fields, and the arithmetic is stated here in the same direction the clause
    states it.
    """
    rows = [(row.window, row.rule, row.detail) for row in log]
    pinned = [(pin.interval, pin.pinned_on) for pin in pins]
    replaced = [(pin.superseded_placement, pin.objective_delta) for pin in pins]
    floors = [
        (area.area_id, area.floor_minutes, area.placed_minutes, area.floor_reservation_minutes)
        for area in areas
    ]
    unheld: list[str] = []
    for clause in block.reason.clauses:
        if isinstance(clause, Blocked):
            if (clause.window, clause.rule, clause.detail) not in rows:
                unheld.append(f"blocked {clause.rule} {clause.window}")
        elif isinstance(clause, Dominant):
            if breakdown is None or clause.term != breakdown.dominant_term():
                unheld.append(f"dominant {clause.term}")
            elif clause.share != breakdown.share_of(clause.term):
                unheld.append(f"dominant share {clause.share}")
        elif isinstance(clause, Bound):
            if clause not in _bound_clauses(block):
                unheld.append(f"bound {clause.selected}")
        elif isinstance(clause, Floor):
            stated = (
                clause.area_id,
                clause.floor_minutes,
                clause.placed,
                clause.of - clause.placed,
            )
            if stated not in floors:
                unheld.append(f"floor {clause.floor_minutes} {clause.placed} {clause.of}")
        elif isinstance(clause, Pinned):
            if (clause.at, clause.pinned_on) not in pinned:
                unheld.append(f"pinned {clause.at}")
        elif (clause.placement, clause.objective_delta) not in replaced:
            unheld.append(f"instead of {clause.placement}")
    return unheld


def _bound_clauses(block: Block) -> tuple[Clause, ...]:
    """The ``bound`` clauses this block already carried, which is where its own come from."""
    return tuple(clause for clause in block.reason.clauses if isinstance(clause, Bound))


class TestTheInstrumentFailsOnAFabricatedClause:
    """The control. Every acceptance below is worthless until the reading rejects something."""

    def test_a_window_no_rule_refused_is_not_traceable(self) -> None:
        result = a_solved_week()
        block = next(block for block in result.document.blocks if block.title == "Walk")
        fabricated = _with_clauses(block, (*block.reason.clauses, Blocked(between(3, 4), "H99")))

        assert untraceable(
            fabricated, log=result.blocked_log, breakdown=result.objective_breakdown
        ) == [f"blocked H99 {between(3, 4)}"]

    def test_a_share_the_breakdown_did_not_compute_is_not_traceable(self) -> None:
        breakdown = a_breakdown(budget_deviation=2.0)
        block = _with_clauses(_a_placed_block(), (Dominant("budget_deviation", 0.5),))

        assert untraceable(block, breakdown=breakdown) == ["dominant share 0.5"]

    def test_a_floor_figure_no_area_holds_is_not_traceable(self) -> None:
        area = a_floored_area()
        block = _with_clauses(_a_placed_block(), (Floor(FITNESS, 240, 120, 999),))

        assert untraceable(block, areas=(area,)) == ["floor 240 120 999"]

    def test_a_real_record_is_traceable(self) -> None:
        """The other half of the control: the reading accepts what the solve did compute."""
        area = a_floored_area(target_minutes=60)
        result = a_solved_week(areas=(area,))

        for block in result.document.blocks:
            assert (
                untraceable(
                    block,
                    log=result.blocked_log,
                    breakdown=result.objective_breakdown,
                    pins=(),
                    areas=(area,),
                )
                == []
            ), block.title


# --------------------------------------------------------------------------------------
# B3: every block carries a reason, over a solved week and over a materialized one
# --------------------------------------------------------------------------------------


class TestEveryBlockCarriesAReason:
    def test_a_fully_solved_week_leaves_no_block_unexplained(self) -> None:
        document = a_solved_week().document

        assert document.blocks
        for block in document.blocks:
            assert block.reason.clauses, block.title

    def test_a_materialized_week_leaves_no_block_unexplained(self) -> None:
        """It runs no search and weighs nothing, so the one ``bound`` clause is the whole reason."""
        week = a_week(
            frame=(a_frame_entry(),),
            anchors=(an_anchor(),),
            template_entries=(a_concrete_entry(),),
        )
        document = materialize(week, cause=MaterializeCause.SOLVE_FAILED)

        assert document.blocks
        for block in document.blocks:
            assert kinds_in(block.reason) == ("Bound",), block.title

    def test_assembling_a_materialized_week_adds_nothing_to_it(self) -> None:
        """Nothing was refused, weighed or pinned, so the projection has nothing to project."""
        week = a_week(frame=(a_frame_entry(),), anchors=(an_anchor(),))
        document = materialize(week, cause=MaterializeCause.SOLVE_FAILED)

        assembled = records_of(document, breakdown=None)

        assert assembled == tuple(block.reason for block in document.blocks)

    def test_a_block_of_every_origin_the_week_holds_is_explained(self) -> None:
        result = solved(
            a_week(
                frame=(a_frame_entry(),),
                anchors=(an_anchor(),),
                shadow_blocks=(a_prep_block(interval=between(9, 10)),),
                template_entries=(a_concrete_entry(),),
                habit_occurrences=(
                    an_occurrence(habit_id=A_HABIT, index=0, area_id=FITNESS, title="Walk"),
                ),
                areas=(an_area_budget(area_id=FITNESS, target_minutes=60),),
            )
        )
        origins = {block.origin.value for block in result.document.blocks}

        assert origins == {"frame", "anchor", "prep", "template_entry", "habit"}
        for block in result.document.blocks:
            assert block.reason.clauses, block.origin


# --------------------------------------------------------------------------------------
# The budget, and the vocabulary it is bounded by
# --------------------------------------------------------------------------------------


class TestTheBudgetIsEnforcedByTheAssembly:
    def test_no_block_of_a_solved_week_exceeds_any_kind_s_budget(self) -> None:
        result = a_solved_week(areas=(a_floored_area(target_minutes=60),))

        for block in result.document.blocks:
            for kind, allowed in CLAUSE_BUDGET.items():
                held = sum(1 for clause in block.reason.clauses if type(clause) is kind)
                assert held <= allowed, (block.title, kind.__name__, held)

    def test_a_log_holding_more_rows_than_a_block_may_report_renders_two(self) -> None:
        """The log is bounded per binding; this bounds what one block renders over its demand.

        A demand spelled by two bindings would otherwise put a third row in front of a reader, and
        the record would be refused rather than truncated.
        """
        result = a_solved_week()
        block = next(block for block in result.document.blocks if block.title == "Walk")
        rows = tuple(_a_row(block, hour) for hour in (3, 4, 5))

        (record,) = records_of(_a_document(block), log=rows)

        assert kinds_in(record).count("Blocked") == CLAUSE_BUDGET[Blocked]
        assert [clause.window for clause in record.clauses if isinstance(clause, Blocked)] == [
            rows[0].window,
            rows[1].window,
        ]

    def test_a_pinned_occurrence_reports_no_refusal_because_nothing_offered_it_again(self) -> None:
        """An occurrence the plan already holds is not a candidate, so no rule ever judged one.

        This is why the whole budget is only reachable through a task: a habit's demand IS the
        occurrence, and a pinned one is placed rather than offered.
        """
        occurrence = an_occurrence(habit_id=A_HABIT, index=0, minutes=60, area_id=FITNESS)
        pin = a_pin(binding=occurrence.binding, interval=between(6, 7))
        result = solved(
            a_week(
                anchors=(an_anchor(interval=between(6, 7)),),
                template_entries=(a_slot(interval=between(6, 7), area_id=FITNESS),),
                habit_occurrences=(occurrence,),
                pins=(pin,),
                areas=(an_area_budget(area_id=FITNESS, target_minutes=300),),
            )
        )

        assert result.blocked_log == ()
        assert "Blocked" not in kinds_in_of(result, occurrence.title)

    def test_the_kinds_the_assembly_can_emit_are_the_six_and_no_more(self) -> None:
        """Bounded by the vocabulary itself rather than by a list of kinds to look for."""
        emitted = _every_kind_a_week_can_produce()

        assert emitted == set(get_args(Clause.__value__))
        assert len(emitted) == len(CLAUSE_BUDGET)

    def test_one_block_can_carry_the_whole_budget(self) -> None:
        """The ceiling is a real record's rather than a number nothing reaches."""
        widest = max(_records_of_the_widest_week(), key=lambda record: len(record.clauses))

        assert len(widest.clauses) == MAX_CLAUSES
        assert kinds_in(widest) == (
            "Bound",
            "Pinned",
            "InsteadOf",
            "Blocked",
            "Blocked",
            "Dominant",
            "Floor",
        )


# --------------------------------------------------------------------------------------
# A derived block reports its determinant and stops
# --------------------------------------------------------------------------------------


class TestADerivedBlockReportsItsDeterminantAndStops:
    def test_a_derived_block_carries_exactly_one_bound_clause(self) -> None:
        result = solved(
            a_week(
                frame=(a_frame_entry(),),
                anchors=(an_anchor(),),
                shadow_blocks=(a_prep_block(interval=between(9, 10)),),
                template_entries=(a_concrete_entry(),),
                habit_occurrences=(
                    an_occurrence(habit_id=A_HABIT, index=0, area_id=FITNESS, title="Walk"),
                ),
                areas=(a_floored_area(target_minutes=60),),
            )
        )
        derived = [block for block in result.document.blocks if block.origin.value != "habit"]

        assert len(derived) == 4
        for block in derived:
            assert kinds_in(block.reason) == ("Bound",), block.title
            assert isinstance(block.reason.clauses[0], Bound)
            assert isinstance(block.reason.clauses[0].source, DerivationSource)

    def test_a_derived_block_the_user_pinned_elsewhere_also_says_so(self) -> None:
        """The one exception the design states, and it is the user's own edit rather than a rule."""
        prep = a_prep_block(interval=between(9, 10), area_id=FITNESS)
        elsewhere = between(15, 16)
        pin = a_pin(
            binding=prep.binding,
            interval=elsewhere,
            superseded_placement=between(9, 10),
            objective_delta=0.75,
        )
        result = solved(
            a_week(
                shadow_blocks=(prep,),
                pins=(pin,),
                areas=(a_floored_area(target_minutes=60),),
            )
        )
        block = next(block for block in result.document.blocks if block.binding == prep.binding)

        assert kinds_in(block.reason) == ("Bound", "Pinned", "InsteadOf")
        assert block.interval == elsewhere

    def test_a_pin_that_replaced_nothing_claims_no_trade(self) -> None:
        prep = a_prep_block(interval=between(9, 10), area_id=FITNESS)
        pin = a_pin(binding=prep.binding, interval=between(15, 16))
        result = solved(a_week(shadow_blocks=(prep,), pins=(pin,)))
        block = next(block for block in result.document.blocks if block.binding == prep.binding)

        assert kinds_in(block.reason) == ("Bound", "Pinned")
        assert block.pinned is False

    def test_a_derived_block_in_a_floored_area_reports_no_floor(self) -> None:
        """A buffer carries an Area, and its placement was still determined rather than chosen."""
        prep = a_prep_block(interval=between(9, 10), area_id=FITNESS)
        result = solved(a_week(shadow_blocks=(prep,), areas=(a_floored_area(),)))
        block = next(block for block in result.document.blocks if block.binding == prep.binding)

        assert kinds_in(block.reason) == ("Bound",)


# --------------------------------------------------------------------------------------
# The floor clause, and the reservation it may not disagree with
# --------------------------------------------------------------------------------------


class TestTheFloorClause:
    def test_it_renders_the_rules_own_floor_and_the_minutes_placed(self) -> None:
        result = a_solved_week(areas=(a_floored_area(target_minutes=60),))
        floor = only(Floor, clauses_of(result, "Walk"))

        assert isinstance(floor, Floor)
        assert (floor.area_id, floor.floor_minutes, floor.placed) == (
            FITNESS,
            DECLARED_FLOOR - IMMOVABLE_MINUTES,
            PLACED_MINUTES,
        )

    def test_the_figure_it_renders_agrees_with_the_probes_reservation(self) -> None:
        """``of`` less ``placed`` IS the reservation, so the two cannot come apart."""
        area = a_floored_area(target_minutes=60)
        week = a_week(
            habit_occurrences=(
                an_occurrence(habit_id=A_HABIT, index=0, minutes=60, area_id=FITNESS, title="Walk"),
            ),
            areas=(area,),
        )
        result = solved(week)
        (reservation,) = week.for_probe().area_floor_reservations
        floor = only(Floor, clauses_of(result, "Walk"))

        assert isinstance(floor, Floor)
        assert floor.of - floor.placed == reservation.reserved_minutes
        assert reservation.area_id == floor.area_id

    def test_an_area_with_no_floor_reports_none(self) -> None:
        result = a_solved_week(areas=(an_area_budget(area_id=FITNESS, target_minutes=60),))

        assert "Floor" not in kinds_in_of(result, "Walk")

    def test_an_area_whose_floor_is_met_reports_none(self) -> None:
        """A floor of no minutes left to reserve neither promoted this content nor refused it."""
        met = a_floored_area(floor_minutes=0, target_minutes=60)
        result = a_solved_week(areas=(met,))

        assert "Floor" not in kinds_in_of(result, "Walk")

    def test_a_block_in_another_area_reports_that_areas_floor(self) -> None:
        result = solved(
            a_week(
                habit_occurrences=(
                    an_occurrence(habit_id=A_HABIT, index=0, area_id=CAREER, title="Leetcode"),
                ),
                areas=(
                    a_floored_area(target_minutes=60),
                    a_floored_area(area_id=CAREER, name="Career", floor_minutes=90),
                ),
            )
        )
        floor = only(Floor, clauses_of(result, "Leetcode"))

        assert isinstance(floor, Floor)
        assert (floor.area_id, floor.floor_minutes) == (CAREER, 90)


# --------------------------------------------------------------------------------------
# The dominant clause: whose cost, and the baseline churn is measured against
# --------------------------------------------------------------------------------------


class TestTheDominantClause:
    def test_it_names_the_term_and_share_the_breakdown_computed(self) -> None:
        result = a_solved_week()
        dominant = only(Dominant, clauses_of(result, "Walk"))
        breakdown = result.objective_breakdown

        assert isinstance(dominant, Dominant)
        assert dominant.term == breakdown.dominant_term()
        assert dominant.share == breakdown.share_of(dominant.term)

    def test_the_share_is_the_terms_fraction_of_what_the_whole_plan_costs(self) -> None:
        """Two charged terms, so the share is a fraction rather than the whole.

        A week with one charged term makes every share 1.0, which a clause carrying a constant
        would satisfy: the fraction is what says the figure came from the breakdown's arithmetic.
        """
        result = a_solved_week()
        two_terms = a_breakdown(budget_deviation=2.0, staleness=1.0)

        (record,) = records_of(_a_document(result.document.blocks[0]), breakdown=two_terms)
        dominant = only(Dominant, record.clauses)

        assert isinstance(dominant, Dominant)
        assert (dominant.term, dominant.share) == ("budget_deviation", 2.0 / 3.0)

    def test_every_chosen_block_of_one_plan_names_the_same_term_and_share(self) -> None:
        """The share is the PLAN's, which is the settlement ticket 1343 asked for.

        Read as this block's cost the two occurrences below would carry different shares, because
        one is in a floored Area and the other is not.
        """
        result = solved(
            a_week(
                habit_occurrences=(
                    an_occurrence(habit_id=A_HABIT, index=0, area_id=FITNESS, title="Walk"),
                    an_occurrence(
                        habit_id=THE_OTHER_HABIT, index=0, area_id=CAREER, title="Leetcode"
                    ),
                ),
                areas=(
                    a_floored_area(target_minutes=60),
                    an_area_budget(area_id=CAREER, name="Career", target_minutes=300),
                ),
            )
        )
        named = {
            (clause.term, clause.share)
            for block in result.document.blocks
            for clause in block.reason.clauses
            if isinstance(clause, Dominant)
        }

        assert len(named) == 1

    def test_a_staleness_dominated_plan_names_the_term_and_neither_of_its_two_inputs(self) -> None:
        """The split knows which input dominated and the record has nowhere to put it.

        Asserted in both directions on purpose. An emptiness alone cannot tell a record that names
        no input from a projection that never ran, so the split's own answer is asserted beside it:
        the reading exists upstream, and ``Dominant`` carries a term, so ``staleness`` is the whole
        of what a block says about a week falling behind.
        """
        stale = a_breakdown(staleness=3.0)

        (record,) = records_of(_a_document(_a_placed_block()), breakdown=stale)
        dominant = only(Dominant, record.clauses)

        assert stale.staleness_split.dominant() is StalenessInput.CADENCE
        assert isinstance(dominant, Dominant)
        assert dominant.term == "staleness"
        assert inputs_named_in(record) == ()

    def test_the_reading_that_finds_an_input_named_in_a_clause_can_see_one(self) -> None:
        # The control. An emptiness over a reading that resolves nothing passes whatever the clauses
        # say, so the reading is shown to find an input where a clause does carry one. A term slot
        # holding an input is exactly the shape the record does not have.
        named = _with_clauses(
            _a_placed_block(), (Dominant(StalenessInput.CADENCE.value, 1.0),)
        ).reason

        assert inputs_named_in(named) == (StalenessInput.CADENCE.value,)

    def test_a_rotation_bound_block_carries_that_as_its_source_and_not_as_the_input(self) -> None:
        """The two spellings are also a habit's binding vocabulary, and that is a different claim.

        A block whose content came from a rotation cursor says so in its ``bound`` clause, which is
        true and is not a statement about which staleness input dominated: the ``dominant`` clause
        still names the term. Without this the emptiness above would read as a rule about the word
        rather than about the clause that may carry it.
        """
        stale = a_breakdown(staleness=3.0)

        (record,) = records_of(_a_document(_a_rotation_bound_block()), breakdown=stale)
        bound = only(Bound, record.clauses)
        dominant = only(Dominant, record.clauses)

        assert isinstance(bound, Bound)
        assert bound.source is BindingSource.ROTATION
        assert isinstance(dominant, Dominant)
        assert dominant.term == "staleness"
        assert inputs_named_in(record) == (StalenessInput.ROTATION.value,)

    def test_a_plan_that_costs_nothing_names_no_dominant_term(self) -> None:
        """A term at a share of zero would state a dominant cost no arithmetic found."""
        result = a_solved_week()
        empty = a_breakdown()

        (record,) = records_of(_a_document(result.document.blocks[0]), breakdown=empty)

        assert "Dominant" not in kinds_in(record)

    def test_a_churn_dominant_clause_names_the_revision_and_its_date(self) -> None:
        result = a_solved_week()
        churned = a_breakdown(churn=4.0)

        (record,) = records_of(_a_document(result.document.blocks[0]), breakdown=churned)
        dominant = only(Dominant, record.clauses)

        assert isinstance(dominant, Dominant)
        assert dominant.baseline is not None
        assert (dominant.baseline.revision_id, dominant.baseline.approved_at) == (
            A_REVISION,
            A_MOMENT,
        )
        assert dominant.baseline.is_measured

    def test_another_term_carries_no_baseline(self) -> None:
        result = a_solved_week()
        dominant = only(Dominant, clauses_of(result, "Walk"))

        assert isinstance(dominant, Dominant)
        assert dominant.term != "churn"
        assert dominant.baseline is None

    def test_a_week_nobody_approved_reports_churn_as_zero_and_names_it_nowhere(self) -> None:
        """Churn is never measured against a proposal nobody approved, so there is no clause."""
        result = a_solved_week()
        breakdown = result.objective_breakdown

        assert breakdown.churn == 0.0
        assert breakdown.churn_baseline.reason == "never-approved"
        assert not any(
            isinstance(clause, Dominant) and clause.term == "churn"
            for block in result.document.blocks
            for clause in block.reason.clauses
        )

    def test_a_week_nothing_weighed_names_no_term(self) -> None:
        week = a_week(frame=(a_frame_entry(),))
        document = materialize(week, cause=MaterializeCause.CHECKPOINT)

        (record,) = records_of(document, breakdown=None)

        assert kinds_in(record) == ("Bound",)


# --------------------------------------------------------------------------------------
# The two pin clauses, read from the pin row rather than recomputed
# --------------------------------------------------------------------------------------


class TestThePinClauses:
    def test_pinned_renders_the_span_and_the_date_the_user_chose(self) -> None:
        occurrence = an_occurrence(habit_id=A_HABIT, index=0, minutes=60, area_id=FITNESS)
        pin = a_pin(binding=occurrence.binding, interval=between(15, 16), day=2)
        result = solved(a_week(habit_occurrences=(occurrence,), pins=(pin,)))
        clause = only(Pinned, clauses_of(result, occurrence.title))

        assert isinstance(clause, Pinned)
        assert (clause.at, clause.pinned_on) == (between(15, 16), on(2))

    def test_instead_of_renders_the_superseded_placement_and_its_delta_verbatim(self) -> None:
        """Both read from the pin. Recomputed, they would be measured under other weights."""
        occurrence = an_occurrence(habit_id=A_HABIT, index=0, minutes=60, area_id=FITNESS)
        pin = a_pin(
            binding=occurrence.binding,
            interval=between(15, 16),
            superseded_placement=between(6, 7),
            objective_delta=0.42,
        )
        result = solved(a_week(habit_occurrences=(occurrence,), pins=(pin,)))
        clause = only(InsteadOf, clauses_of(result, occurrence.title))

        assert isinstance(clause, InsteadOf)
        assert (clause.placement, clause.objective_delta) == (between(6, 7), 0.42)

    def test_a_block_nobody_pinned_reports_neither(self) -> None:
        result = a_solved_week()

        assert "Pinned" not in kinds_in_of(result, "Walk")
        assert "InsteadOf" not in kinds_in_of(result, "Walk")

    @pytest.mark.parametrize(
        ("superseded_placement", "objective_delta"),
        [(None, 0.42), ("a span", None)],
        ids=["a delta with no placement", "a placement with no delta"],
    )
    def test_half_a_superseded_pair_claims_no_trade(
        self, superseded_placement: str | None, objective_delta: float | None
    ) -> None:
        """Half a pair renders half a sentence, so the record states the edit and stops.

        The same pairing ``Block.pinned`` is set from, asserted from both sides: a stored pin can
        carry either half alone, and neither half alone is a trade the panel can render.
        """
        occurrence = an_occurrence(habit_id=A_HABIT, index=0, minutes=60, area_id=FITNESS)
        pin = a_pin(
            binding=occurrence.binding,
            interval=between(15, 16),
            superseded_placement=None if superseded_placement is None else between(6, 7),
            objective_delta=objective_delta,
        )
        result = solved(a_week(habit_occurrences=(occurrence,), pins=(pin,)))
        block = next(
            block for block in result.document.blocks if block.binding == occurrence.binding
        )

        assert "Pinned" in kinds_in(block.reason)
        assert "InsteadOf" not in kinds_in(block.reason)
        assert block.pinned is False

    def test_the_span_the_clause_names_is_the_span_the_week_holds_the_block_at(self) -> None:
        """For a binding that has BEGUN and is pinned elsewhere, which is where the two could part.

        The clause renders the pin's own interval. It agrees with the block's because the inherited
        set seeds a pinned block at the pin unconditionally, and ``immovability``'s prose describes
        the opposite precedence for this exact input: a started binding whose pin is refused. Which
        module is right is ticket 1333's question, and this assertion is what makes the answer
        visible here instead of silently rendering a span the week does not hold.
        """
        occurrence = an_occurrence(habit_id=A_HABIT, index=0, minutes=60, area_id=FITNESS)
        began = between(9, 10)
        pinned_at = between(15, 16)
        week = a_week(
            now=began.end,
            habit_occurrences=(occurrence,),
            live_plan=a_live_plan(
                a_block(binding=occurrence.binding, interval=began, title=occurrence.title)
            ),
            pins=(
                a_pin(
                    binding=occurrence.binding,
                    interval=pinned_at,
                    # The pair a real pin carries, so `at` has a second span to be confused with:
                    # the placement the edit replaced is exactly where this block had begun.
                    superseded_placement=began,
                    objective_delta=0.42,
                ),
            ),
        )
        result = solved(week)
        block = next(
            block for block in result.document.blocks if block.binding == occurrence.binding
        )
        clause = only(Pinned, block.reason.clauses)

        # The precondition, asserted rather than assumed: without it this is a test about an
        # ordinary pin and the precedence it exists for is never reached.
        assert occurrence.binding in PartialPlan.of(week).started
        assert isinstance(clause, Pinned)
        assert clause.at == block.interval
        assert clause.at == pinned_at
        assert clause.at != began

    def test_the_pin_glyph_and_the_instead_of_clause_are_the_same_pairing(self) -> None:
        """``Block.pinned`` is set from the pair, so the two cannot report different things."""
        occurrence = an_occurrence(habit_id=A_HABIT, index=0, minutes=60, area_id=FITNESS)
        traded = a_pin(
            binding=occurrence.binding,
            interval=between(15, 16),
            superseded_placement=between(6, 7),
            objective_delta=0.42,
        )
        result = solved(a_week(habit_occurrences=(occurrence,), pins=(traded,)))
        block = next(
            block for block in result.document.blocks if block.binding == occurrence.binding
        )

        assert block.pinned is True
        assert ("InsteadOf" in kinds_in(block.reason)) == block.pinned


# --------------------------------------------------------------------------------------
# The yield of a strong preference, in the vocabulary that already exists
# --------------------------------------------------------------------------------------


class TestAStrongWindowThatCouldNotBeHonored:
    def test_the_three_clauses_section_08_prints_are_reproducible(self) -> None:
        """The rejected preferred windows, the constraints that refused them, and the cost.

        Section 08's own example. The rules and the windows are asserted verbatim; the misfit's
        share is 1.0 here rather than the section's illustrative 62%, because every other term of
        this week is zero by construction and a share is a fraction of what the plan costs.
        """
        result = solved(preference_yield_week())
        clauses = clauses_of(result, f"Gym · {VARIANT}")
        blocked = [clause for clause in clauses if isinstance(clause, Blocked)]
        dominant = only(Dominant, clauses)

        assert [(clause.window, clause.rule, clause.detail) for clause in blocked] == [
            (EARLY, "anchor_overlap", COMMITMENT),
            (MIDDAY, "area_daily_cap", "Fitness, 120m against a 60m cap on 2026-02-09"),
        ]
        assert isinstance(dominant, Dominant)
        assert (dominant.term, dominant.share) == ("time_of_day_misfit", 1.0)

    def test_the_occurrence_is_placed_anyway_because_a_preference_is_a_cost(self) -> None:
        result = solved(preference_yield_week())
        block = next(block for block in result.document.blocks if block.title == f"Gym · {VARIANT}")

        assert block.interval == PLACED_AT
        assert not block.interval.overlaps(EARLY)
        assert not block.interval.overlaps(MIDDAY)

    def test_the_yield_needs_no_seventh_clause_kind(self) -> None:
        result = solved(preference_yield_week())
        carried = {
            type(clause) for block in result.document.blocks for clause in block.reason.clauses
        }

        assert carried <= set(get_args(Clause.__value__))
        assert len(get_args(Clause.__value__)) == len(CLAUSE_BUDGET) == 6


# --------------------------------------------------------------------------------------
# Boundaries: the text a clause carries, and two clauses that tie
# --------------------------------------------------------------------------------------


class TestWhatABoundaryInputDoesToTheBudget:
    def test_a_title_longer_than_the_panel_is_still_one_clause(self) -> None:
        """The budget counts clauses, not characters: text is bounded where text is stored."""
        long_title = "Gym " * 3_000
        occurrence = an_occurrence(
            habit_id=A_HABIT, index=0, minutes=60, area_id=FITNESS, title=long_title
        )
        result = solved(a_week(habit_occurrences=(occurrence,)))
        clauses = clauses_of(result, long_title)
        bound = only(Bound, clauses)

        assert isinstance(bound, Bound)
        assert bound.selected == long_title
        assert len(clauses) <= MAX_CLAUSES

    @pytest.mark.parametrize(
        "title",
        ["Gym\x1b[31m", "Gym\u200b", "Gym\r\nSquats", "Gym\tSquats", "Gym\u202eydoB"],
        ids=["C1 escape", "zero width", "CRLF", "tab", "a bidi override"],
    )
    def test_a_title_carrying_control_characters_reaches_the_clause_unchanged(
        self, title: str
    ) -> None:
        """No scrubbing here. Fitting text to a column is a boundary concern with its own home.

        A second definition of a control-character class in this package would diverge from that
        one the first time either changed, so the clause carries what the producer resolved.
        """
        occurrence = an_occurrence(
            habit_id=A_HABIT, index=0, minutes=60, area_id=FITNESS, title=title
        )
        result = solved(a_week(habit_occurrences=(occurrence,)))
        bound = only(Bound, clauses_of(result, title))

        assert isinstance(bound, Bound)
        assert bound.selected == title

    def test_two_refusals_that_tie_on_kind_keep_the_order_they_were_recorded_in(self) -> None:
        result = a_solved_week()
        block = next(block for block in result.document.blocks if block.title == "Walk")
        first, second = _a_row(block, 3), _a_row(block, 4)

        (record,) = records_of(_a_document(block), log=(first, second))
        (reversed_record,) = records_of(_a_document(block), log=(second, first))

        assert [clause.window for clause in record.clauses if isinstance(clause, Blocked)] == [
            first.window,
            second.window,
        ]
        assert [
            clause.window for clause in reversed_record.clauses if isinstance(clause, Blocked)
        ] == [second.window, first.window]


class TestWhatTheModuleIsBoundedBy:
    """The two figures and the one term name this module shares with something that owns them."""

    def test_the_log_keeps_exactly_as_many_rows_as_a_block_may_report(self) -> None:
        """Both derive from the clause budget, so neither can be raised without the other.

        The log's bound exists BECAUSE the record renders two, which the attempt's own comment
        states. Stated in two modules and asserted here, a third row could be kept and never read.
        """
        assert BLOCKED_PER_BLOCK == ROWS_PER_BINDING == CLAUSE_BUDGET[Blocked]

    def test_the_term_the_baseline_is_named_for_is_one_the_objective_computes(self) -> None:
        """A second spelling of a name the weight set owns, crossed rather than trusted."""
        assert CHURN in OBJECTIVE_TERMS
        assert CHURN in a_breakdown().costs()


# --------------------------------------------------------------------------------------
# The projection is pure, and it changes nothing but the reason
# --------------------------------------------------------------------------------------


class TestTheProjectionItself:
    def test_assembling_twice_produces_the_same_records(self) -> None:
        area = a_floored_area(target_minutes=60)
        result = a_solved_week(areas=(area,))

        once = records_of(
            result.document,
            log=result.blocked_log,
            breakdown=result.objective_breakdown,
            areas=(area,),
        )
        twice = records_of(
            result.document,
            log=result.blocked_log,
            breakdown=result.objective_breakdown,
            areas=(area,),
        )

        assert once == twice

    def test_the_order_the_pins_and_the_areas_arrive_in_changes_nothing(self) -> None:
        occurrence = an_occurrence(habit_id=A_HABIT, index=0, minutes=60, area_id=FITNESS)
        pins = (
            a_pin(binding=occurrence.binding, interval=between(15, 16)),
            a_pin(binding=BindingRef.for_habit(THE_OTHER_HABIT, index=0), interval=between(2, 3)),
        )
        areas = (
            a_floored_area(target_minutes=60),
            a_floored_area(area_id=CAREER, name="Career", floor_minutes=90),
        )
        result = solved(a_week(habit_occurrences=(occurrence,), areas=areas))

        forwards = records_of(result.document, pins=pins, areas=areas)
        backwards = records_of(
            result.document, pins=tuple(reversed(pins)), areas=tuple(reversed(areas))
        )

        assert forwards == backwards

    def test_a_plan_keeps_every_block_it_had_and_changes_only_the_reason(self) -> None:
        result = a_solved_week()
        plan = result.document

        explained_plan = explained(
            plan,
            blocked_log=result.blocked_log,
            breakdown=result.objective_breakdown,
            pins=(),
            areas=(an_area_budget(area_id=FITNESS, target_minutes=60),),
        )

        assert [block.id for block in explained_plan.blocks] == [block.id for block in plan.blocks]
        assert [block.interval for block in explained_plan.blocks] == [
            block.interval for block in plan.blocks
        ]
        assert [block.title for block in explained_plan.blocks] == [
            block.title for block in plan.blocks
        ]

    def test_each_record_reaches_the_block_it_was_assembled_for(self) -> None:
        area = a_floored_area(target_minutes=60)
        result = solved(
            a_week(
                frame=(a_frame_entry(),),
                habit_occurrences=(
                    an_occurrence(habit_id=A_HABIT, index=0, minutes=60, area_id=FITNESS),
                ),
                areas=(area,),
            )
        )
        plan = result.document

        records = assemble(
            plan,
            blocked_log=result.blocked_log,
            breakdown=result.objective_breakdown,
            pins=(),
            areas=(area,),
        )
        rebuilt = explained(
            plan,
            blocked_log=result.blocked_log,
            breakdown=result.objective_breakdown,
            pins=(),
            areas=(area,),
        )

        assert [block.reason for block in rebuilt.blocks] == list(records)


# --------------------------------------------------------------------------------------
# Builders that need the module above them
# --------------------------------------------------------------------------------------


def kinds_in_of(result: SolveResult, title: str) -> tuple[str, ...]:
    return tuple(type(clause).__name__ for clause in clauses_of(result, title))


def _with_clauses(block: Block, clauses: Sequence[Clause]) -> Block:
    from dataclasses import replace

    from syncr_domain.reasons import ReasonRecord

    return replace(block, reason=ReasonRecord(tuple(clauses)))


def _a_document(block: Block) -> PlanDocument:
    from dataclasses import replace

    return replace(_a_solved_document(), blocks=(block,))


def _a_solved_document() -> PlanDocument:
    return a_solved_week().document


def _a_placed_block() -> Block:
    result = a_solved_week()
    return next(block for block in result.document.blocks if block.title == "Walk")


def _a_rotation_bound_block() -> Block:
    """One block whose content a rotation cursor chose, found by the clause rather than the title.

    The title is composed by the solver from the habit's and the variant's, so selecting on it would
    pin a spelling this test is not about.
    """
    result = a_solved_week(
        habit_occurrences=(
            an_occurrence(habit_id=A_HABIT, index=0, area_id=FITNESS, title="Gym", variant="Legs"),
        )
    )
    return next(
        block
        for block in result.document.blocks
        if any(
            isinstance(clause, Bound) and clause.source is BindingSource.ROTATION
            for clause in block.reason.clauses
        )
    )


def _a_row(block: Block, hour: float) -> BlockedCandidate:
    return BlockedCandidate.of(
        block.binding,
        Rejection(ConstraintRule.BLOCK_OVERLAP, between(hour, hour + 1), "Sleep"),
    )


def _the_widest_week() -> SolveInputs:
    """A week where one block carries every kind of clause the vocabulary has.

    A pinned chunk of a divided task, in a partly served Area, whose own DEMAND was refused twice
    before the rest of it was packed: seven clauses, which is the whole budget. A pinned HABIT
    occurrence cannot reach seven, and the reason is worth stating: an occurrence the plan already
    holds is not offered again, so nothing is ever refused for it. A task's demand outlives the
    piece the pin holds, so the refusals recorded while it was packed belong to the pinned chunk as
    much as to any other.
    """
    task = an_eligible_task(
        task_id=A_TASK_OF_ITS_OWN,
        remaining_minutes=180,
        min_chunk_minutes=60,
        area_id=FITNESS,
        title="Lab Report",
    )
    return a_week(
        anchors=(an_anchor(interval=between(6, 7)),),
        template_entries=(a_slot(interval=between(6, 7), area_id=FITNESS),),
        eligible_tasks=(task,),
        areas=(a_floored_area(target_minutes=300, max_per_day_minutes=60),),
        pins=(
            a_pin(
                binding=task.binding,
                interval=between(15, 16),
                superseded_placement=between(6, 7),
                objective_delta=0.42,
            ),
        ),
    )


def _records_of_the_widest_week() -> tuple[ReasonRecord, ...]:
    week = _the_widest_week()
    result = solved(week)
    return records_of(
        result.document,
        log=result.blocked_log,
        breakdown=result.objective_breakdown,
        pins=week.pins,
        areas=week.areas,
    )


def _every_kind_a_week_can_produce() -> set[type]:
    return {type(clause) for record in _records_of_the_widest_week() for clause in record.clauses}
