"""The golden file: the reference week solved against the shipped weights, block by block.

A whole output shape matters here, so the assertion is a stored document rather than a handful of
figures. Every block, every unfilled slot, every refusal, the seven costs and the verdict are
rendered as text and compared against ``reference_week_golden.txt``, so a change to any of them is a
readable diff rather than a number that moved.

**The rendering is deliberately not the document's ``repr``.** A repr carries derived identities and
field order, so it changes when an unrelated field is added and it is unreadable when it differs.
This renders what a reader can check against the fixture: the local day, the wall times, what the
block is, its Area, its title, and what its ``bound`` clause says determined it.

The tests beside the golden file are the ones a stored file cannot make: that the composition is the
one the fixture's table claims, that the eight shapes the fixture exists for are all present in the
output, and that solving it twice produces the same text.

**The reason records are rendered as a census rather than block by block.** Every clause of every
block would add sixty lines whose values repeat, because the ``dominant`` clause names the plan and
the ``floor`` clause names an Area: what changes when an attachment rule changes is the COUNT per
kind and the widest record, so those are what the file holds. The clauses of the blocks that carry
more than one are asserted here instead, where the assertion can name the block.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Final

from syncr_domain.feasibility import Provenance
from syncr_domain.identity import BindingRef, Origin
from syncr_domain.reasons import CLAUSE_BUDGET, MAX_CLAUSES, Blocked, Bound, Floor
from syncr_solver import solve
from tests.objective_weeks import hand_tuned_weights
from tests.reference_week import (
    CAREER,
    FITNESS,
    GYM,
    INTERVIEW,
    LONDON,
    PAST_PAPERS,
    PINS,
    STUDY,
    TIMED_BLOCKS,
    reference_week,
)

if TYPE_CHECKING:
    from syncr_domain.plan import Block
    from syncr_domain.reasons import Clause
    from syncr_solver.solve import SolveResult

GOLDEN: Final = Path(__file__).with_name("reference_week_golden.txt")

# A clause kind as the design language names it: the spec's rows read `instead of`, not the type's
# own spelling. Split on the capitals rather than mapped, so a seventh kind would need no table.
_CAMEL_BOUNDARY: Final = re.compile(r"(?<!^)(?=[A-Z])")

_AREAS: Final = {FITNESS: "Fitness", CAREER: "Career", STUDY: "Study"}


def solved_reference() -> SolveResult:
    """The reference week under weight set version 1, at the shipped budget."""
    return solve(reference_week(), hand_tuned_weights())


def local(block: Block) -> str:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(LONDON)
    start = block.interval.start.astimezone(zone)
    end = block.interval.end.astimezone(zone)
    return f"{start:%a %H:%M}-{end:%H:%M}"


def area_of(block: Block) -> str:
    return "-" if block.area_id is None else _AREAS.get(block.area_id, str(block.area_id))


def clause_of(block: Block) -> str:
    clause = block.reason.clauses[0]
    if not isinstance(clause, Bound):
        return type(clause).__name__.lower()
    return f"bound {clause.source.value} · {clause.selected}"


def clause_census(result: SolveResult) -> Counter[str]:
    """How many clauses of each kind the week's records hold in all."""
    counted: Counter[str] = Counter()
    for block in result.document.blocks:
        counted.update(type(clause).__name__ for clause in block.reason.clauses)
    return counted


def clause_label(kind: type[Clause]) -> str:
    return _CAMEL_BOUNDARY.sub(" ", kind.__name__).lower()


def rendered(result: SolveResult) -> str:
    """This result as the golden file holds it: the plan, the gaps, the refusals, and the cost."""
    document = result.document
    lines = [
        f"week {document.iso_week}  discretionary {document.discretionary_minutes}m  "
        f"unallocated {document.unallocated_minutes}m  "
        f"oversubscription {document.oversubscription_minutes}m",
        f"blocks {len(document.blocks)}  slots {len(document.empty_slots)}  "
        f"windows {len(document.forbidden_windows)}  blocked {len(result.blocked_log)}",
        "",
        "BLOCKS",
    ]
    lines += [
        f"  {local(block):17} {block.origin.value:15} {area_of(block):8} "
        f"{block.title:34} {clause_of(block)}"
        for block in document.blocks
    ]
    lines += ["", "EMPTY SLOTS"]
    lines += [
        f"  {slot.interval.start:%a %H:%M}-{slot.interval.end:%H:%M} "
        f"{_AREAS.get(slot.area_id, str(slot.area_id)):8} {slot.reason.value}"
        for slot in document.empty_slots
    ] or ["  none"]
    lines += ["", "BLOCKED"]
    lines += [f"  {row.rule.value:22} {row.detail}" for row in result.blocked_log] or ["  none"]
    lines += ["", "REASONS"]
    census = clause_census(result)
    lines += [
        f"  {clause_label(kind):12} {census[kind.__name__]:4}   at most {allowed} per block"
        for kind, allowed in CLAUSE_BUDGET.items()
    ]
    widest = max(document.blocks, key=lambda block: len(block.reason.clauses))
    lines += [
        f"  {'clauses':12} {sum(census.values()):4}   over {len(document.blocks)} blocks",
        f"  widest       {len(widest.reason.clauses):4}   {widest.title}",
    ]
    lines += ["", "OBJECTIVE"]
    lines += [
        f"  {term:20} {cost:.6f}" for term, cost in result.objective_breakdown.costs().items()
    ]
    lines += [
        f"  {'TOTAL':20} {result.objective_breakdown.total():.6f}",
        f"  dominant {result.objective_breakdown.dominant_term()}",
        "",
        "VERDICT",
        f"  {result.verdict.provenance.value}  feasible={result.verdict.feasible}  "
        f"shortfalls={len(result.verdict.shortfalls)}",
    ]
    lines += [
        f"  {shortfall.kind.value:28} {shortfall.minutes}m against {', '.join(shortfall.against)}"
        for shortfall in result.verdict.shortfalls
    ]
    lines += ["", f"ITERATIONS {result.iterations}", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# The golden file
# --------------------------------------------------------------------------------------


def test_the_reference_week_solves_to_the_stored_document() -> None:
    """Regenerate with ``python -m tests.regenerate_golden`` after a deliberate change."""
    assert rendered(solved_reference()) == GOLDEN.read_text(encoding="utf-8")


def test_the_stored_document_is_not_empty() -> None:
    # The control for the assertion above: an empty file would make it a claim about nothing.
    assert len(GOLDEN.read_text(encoding="utf-8").splitlines()) > 60


def test_solving_the_reference_week_twice_renders_the_same_text() -> None:
    assert rendered(solved_reference()) == rendered(solved_reference())


# --------------------------------------------------------------------------------------
# What the fixture claims about itself
# --------------------------------------------------------------------------------------


def test_the_document_holds_the_timed_blocks_the_fixtures_table_claims() -> None:
    assert len(solved_reference().document.blocks) == TIMED_BLOCKS


def test_the_composition_is_the_one_the_fixtures_table_states() -> None:
    counted = Counter(block.origin.value for block in solved_reference().document.blocks)

    assert dict(counted) == {
        Origin.FRAME.value: 7,
        Origin.TEMPLATE_ENTRY.value: 19,
        Origin.ANCHOR.value: 12,
        Origin.PREP.value: 1,
        Origin.TRANSIT.value: 2,
        Origin.HABIT.value: 15,
        Origin.TASK.value: 5,
    }


def test_the_fifteen_minute_compact_block_is_in_the_output() -> None:
    document = solved_reference().document

    assert any(
        block.title == "Wake Up" and block.interval.total_minutes() == 15
        for block in document.blocks
    )


def test_the_interview_anchor_carries_its_prep_its_two_transit_legs_and_its_recovery() -> None:
    document = solved_reference().document
    derived = [block for block in document.blocks if block.binding.entity_id == INTERVIEW]

    assert sorted(block.origin.value for block in derived) == [
        Origin.ANCHOR.value,
        Origin.PREP.value,
        Origin.TRANSIT.value,
        Origin.TRANSIT.value,
    ]
    assert [window.anchor_id for window in document.forbidden_windows] == [INTERVIEW]


def test_the_journey_home_sits_inside_its_own_commitments_recovery_window() -> None:
    """Recovery is measured from the commitment rather than from the journey, so it sits inside."""
    document = solved_reference().document
    window = document.forbidden_windows[0]
    home = next(block for block in document.blocks if block.title == "Go Home")

    assert home.interval.overlaps(window.interval)


def test_the_anchor_conflict_refuses_two_entries_and_names_the_commitment() -> None:
    result = solved_reference()
    refused = [row for row in result.blocked_log if row.detail == "Formal Methods"]

    assert len(refused) == 2
    assert {row.rule.value for row in refused} == {"anchor_overlap"}


def test_the_week_holds_an_overlap_three_deep_that_no_solver_placement_created() -> None:
    """Two commitments over one night: an overlap in a solved week is the user's or an anchor's."""
    document = solved_reference().document
    edges = sorted(
        (moment, delta)
        for block in document.blocks
        for moment, delta in ((block.interval.start, 1), (block.interval.end, -1))
    )
    depth = 0
    deepest = 0
    for _, delta in edges:
        depth += delta
        deepest = max(deepest, depth)

    assert deepest == 3


def test_the_pinned_habit_is_at_its_pin_and_says_what_it_replaced() -> None:
    document = solved_reference().document
    pin = PINS[0]
    pinned = next(block for block in document.blocks if block.binding == pin.binding)

    assert pinned.interval == pin.interval
    assert pinned.pinned is True
    assert pinned.superseded_placement == pin.superseded_placement
    assert pinned.objective_delta == pin.objective_delta


def test_the_pinned_habit_appears_exactly_once() -> None:
    """The demand a pin holds is the occurrence itself, so nothing offers it a second window."""
    document = solved_reference().document

    assert sum(1 for block in document.blocks if block.binding == PINS[0].binding) == 1


def test_the_queue_bound_habit_names_the_backlog_item_it_drew() -> None:
    document = solved_reference().document
    drawn = [block for block in document.blocks if block.title.startswith("Leetcode")]

    assert len(drawn) == 4
    assert {block.title for block in drawn} == {"Leetcode · Placement Admin"}


def test_the_frame_span_the_preceding_week_owns_holds_time_this_week_cannot_place_in() -> None:
    """This week has the hours and not the occurrence, so nothing is placed inside them."""
    week = reference_week()
    document = solved_reference().document
    overhang = week.frame_overhang[0]

    assert not any(block.interval.overlaps(overhang) for block in document.blocks)


def test_the_rotation_bound_habit_names_the_variant_its_cursor_resolved() -> None:
    document = solved_reference().document
    rotated = [block for block in document.blocks if block.binding.entity_id == GYM]

    assert {block.title for block in rotated} == {"Gym · Push", "Gym · Pull", "Gym · Legs"}
    assert len(rotated) == 5


def test_the_verdict_is_authoritative_and_the_week_packs() -> None:
    verdict = solved_reference().verdict

    assert verdict.provenance is Provenance.SOLVER
    assert verdict.feasible is True


def test_every_overlap_the_week_holds_is_the_users_own_or_two_commitments() -> None:
    """H4 binds the solver rather than the plan, so an overlap is never one a solve created.

    The reference week holds two: the Friday lectures over the Friday night frame, which is the
    depth-3 shape, and the pinned ``Gym`` over that morning's ``Wake Up`` entry, which is the user's
    own. Nothing else in it overlaps anything, and this is the assertion that says so.
    """
    space = {Origin.FRAME, Origin.ANCHOR}
    blocks = solved_reference().document.blocks

    for index, earlier in enumerate(blocks):
        for later in blocks[index + 1 :]:
            if not earlier.interval.overlaps(later.interval):
                continue
            excused = earlier.pinned or later.pinned or {earlier.origin, later.origin} <= space
            assert excused, (earlier.title, later.title)


def test_every_block_carries_at_least_one_clause() -> None:
    for block in solved_reference().document.blocks:
        assert block.reason.clauses, block.title


# --------------------------------------------------------------------------------------
# The reason records, over a real week
# --------------------------------------------------------------------------------------


def test_no_block_of_the_week_exceeds_any_clause_kind_s_budget() -> None:
    """The budget, per kind, over every block of the golden week rather than over a fixture."""
    for block in solved_reference().document.blocks:
        for kind, allowed in CLAUSE_BUDGET.items():
            held = sum(1 for clause in block.reason.clauses if type(clause) is kind)
            assert held <= allowed, (block.title, kind.__name__, held)
        assert len(block.reason.clauses) <= MAX_CLAUSES, block.title


def test_the_census_the_golden_file_holds_is_the_one_the_records_carry() -> None:
    # The control for the rendered census: a reading that counted nothing would still render.
    census = clause_census(solved_reference())

    assert census["Bound"] == TIMED_BLOCKS
    assert sum(census.values()) > TIMED_BLOCKS


def test_every_derived_block_carries_its_determinant_and_nothing_else() -> None:
    """Its placement was determined, so there is nothing else about it to report."""
    chosen = {Origin.HABIT, Origin.TASK}

    for block in solved_reference().document.blocks:
        if block.origin in chosen:
            continue
        assert len(block.reason.clauses) == 1, (block.title, block.reason.clauses)
        assert isinstance(block.reason.clauses[0], Bound)


def test_the_pinned_habit_reports_the_pin_and_what_it_replaced() -> None:
    pin = PINS[0]
    block = next(
        block for block in solved_reference().document.blocks if block.binding == pin.binding
    )
    kinds = [type(clause).__name__ for clause in block.reason.clauses]

    assert kinds == ["Bound", "Pinned", "InsteadOf", "Dominant", "Floor"]


def test_every_chunk_of_the_divided_task_reports_the_demand_s_refused_windows() -> None:
    """The refusals were recorded against the demand, and a chunk is one piece of that demand.

    Paired by binding rather than by demand they would reach the first chunk and no other, so a
    reader selecting the second piece of a task would be told nothing about what was tried for it.
    """
    chunks = [
        block
        for block in solved_reference().document.blocks
        if block.binding.entity_id == PAST_PAPERS
    ]
    refused = {_refused_windows(block) for block in chunks}

    assert len(chunks) > 1
    assert len(refused) == 1
    assert refused != {()}


def test_the_floor_clause_agrees_with_the_probes_reservation_for_the_same_area() -> None:
    """``of`` less ``placed`` IS the reservation, over every Area the week's blocks are charged to.

    The two figures come from one netting set, which is what stops the clause disagreeing with the
    figure a reader compares it against. Crossed against the probe's own projection rather than
    against the inputs, because the projection is what a verdict is read from.
    """
    reserved = {
        reservation.area_id: reservation.reserved_minutes
        for reservation in reference_week().for_probe().area_floor_reservations
    }
    floors = [
        clause
        for block in solved_reference().document.blocks
        for clause in block.reason.clauses
        if isinstance(clause, Floor)
    ]

    assert floors
    for clause in floors:
        assert clause.of - clause.placed == reserved[clause.area_id], clause


def test_no_clause_names_a_rule_outside_the_checkers_vocabulary() -> None:
    """Every ``blocked`` clause names a window and a rule the log holds, and the log is bounded."""
    result = solved_reference()
    recorded = {(row.window, row.rule, row.detail) for row in result.blocked_log}

    for block in result.document.blocks:
        for clause in block.reason.clauses:
            if isinstance(clause, Blocked):
                assert (clause.window, clause.rule, clause.detail) in recorded, clause


def _refused_windows(block: Block) -> tuple[tuple[object, str], ...]:
    return tuple(
        (clause.window, clause.rule)
        for clause in block.reason.clauses
        if isinstance(clause, Blocked)
    )


def test_the_document_holds_one_block_per_identity() -> None:
    document = solved_reference().document

    assert len(document.blocks_by_id()) == len(document.blocks)


def test_the_bindings_the_document_holds_are_the_ones_the_fixture_names() -> None:
    # The control that the identities are not accidental: a pin pairs on one, and an outcome too.
    document = solved_reference().document

    assert BindingRef.for_habit(GYM, index=0) in {block.binding for block in document.blocks}
