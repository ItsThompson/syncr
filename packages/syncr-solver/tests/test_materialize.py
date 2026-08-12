"""``materialize``: what a week holds when nothing has been chosen, and why each part is there.

Every test drives the entry point with literal inputs. There is no clock, no repository and no
weight set anywhere in this suite, because there is none in the code it exercises: that is what
makes a materialized week reproducible from stored data, and it is why this phase could be built
before the solver exists.

**Traceability.** The criterion these tests carry is that a degraded plan still explains itself,
which is verified by scenario S24 and story US-SOLVE-10. It is NOT S32 or US-SOLVE-11: those are
the recovery window's scope and the stability of a re-solve, and neither is about a plan derived
without a solver.

The figures a document carries, and the determinism property over them, are in
``test_materialized_figures.py``. This file is about what is placed, what is refused, and what
each block says about itself.
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from syncr_domain.gaps import EmptySlotReason, ForbiddenScope, SlotContext, gutter_label
from syncr_domain.identity import BindingKind, BindingRef, Origin, TransitLeg, block_id
from syncr_domain.reasons import Bound, DerivationSource
from syncr_solver import materialize
from syncr_solver.constraints import ConstraintRule
from syncr_solver.errors import MaterializeError
from syncr_solver.inputs import FrameEntry
from syncr_solver.materialize import Materialization, derive
from syncr_solver.metrics import MATERIALIZE_TOTAL, MaterializeCause
from tests.materialized_weeks import (
    CAREER,
    FITNESS,
    WEEK,
    a_block,
    a_concrete_entry,
    a_frame_entry,
    a_live_plan,
    a_prep_block,
    a_recovery_window,
    a_slot,
    a_transit_block,
    an_anchor,
    between,
    inputs,
    on,
    zones,
)

if TYPE_CHECKING:
    from syncr_domain.plan import Block, PlanDocument
    from syncr_domain.reasons import Clause
    from syncr_solver.inputs import SolveInputs

# The origins derivation determines. Every block a materialized week holds is one of these four,
# and the three that are not here -- a habit, a task, and a slot's late-bound content -- are what
# content binding adds.
DERIVED_ORIGINS = frozenset({Origin.FRAME, Origin.ANCHOR, Origin.PREP, Origin.TRANSIT})


def rendered(clause: Bound) -> str:
    """One ``bound`` row as the panel lays it out: the source, then what it determined.

    The template catalog itself is the interface's, one template per clause kind. What this states
    is the row's shape, so an assertion about a clause is an assertion about what a reader sees
    rather than about a field name.
    """
    return f"{clause.source.value} · {clause.selected}"


def only_clause(block: Block) -> Clause:
    assert len(block.reason.clauses) == 1, block.reason.clauses
    return block.reason.clauses[0]


def bound_clause(block: Block) -> Bound:
    clause = only_clause(block)
    assert isinstance(clause, Bound)
    return clause


def a_week(**overrides: object) -> SolveInputs:
    """A week holding one of everything derivation can determine, none of it colliding."""
    anchor = an_anchor(interval=between(10, 11))
    stated: dict[str, object] = {
        "frame": (a_frame_entry(interval=between(23, 31)),),
        "anchors": (anchor,),
        "shadow_blocks": (
            a_transit_block(anchor_id=anchor.anchor_id, interval=between(9.5, 10)),
            a_prep_block(anchor_id=anchor.anchor_id, interval=between(8, 9)),
        ),
        "forbidden_windows": (a_recovery_window(interval=between(11, 12)),),
        "template_entries": (a_concrete_entry(interval=between(6.75, 7)), a_slot()),
    }
    stated.update(overrides)
    return inputs(**stated)


def blocks_by_origin(document: PlanDocument) -> dict[Origin, list[Block]]:
    found: dict[Origin, list[Block]] = {}
    for block in document.blocks:
        found.setdefault(block.origin, []).append(block)
    return found


# --------------------------------------------------------------------------------
# The interface
# --------------------------------------------------------------------------------


def test_materialize_takes_a_snapshot_and_a_cause_and_no_weight_set() -> None:
    # There is nothing to weigh when nothing is being chosen, and that is the whole reason this
    # phase is usable before the objective exists. Asserted over the signature's inventory, so a
    # weight set cannot arrive as an optional argument nobody notices.
    parameters = inspect.signature(materialize).parameters

    assert set(parameters) == {"inputs", "cause"}
    assert parameters["cause"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["cause"].default is inspect.Parameter.empty


def test_nothing_in_the_document_depends_on_the_instant_the_week_was_assembled_against() -> None:
    # The observable half of "no clock". `now` decides which blocks have started, which is a
    # question about moving one, and derivation moves nothing: one snapshot re-stamped with another
    # instant materializes identically.
    week = a_week()

    monday = materialize(week, cause=MaterializeCause.PHASE1)
    friday = materialize(
        dataclasses.replace(week, now=between(0, 1, day=4).start), cause=MaterializeCause.PHASE1
    )

    assert monday == friday


def test_each_cause_counts_its_own_materializations() -> None:
    # `solve_failed` is expected to sit at zero, so it has to be countable apart from the two
    # ordinary causes: a non-zero value is a solver fault surfacing as a degraded plan rather than
    # as an outage.
    before = {cause: _counted(cause) for cause in MaterializeCause}

    materialize(a_week(), cause=MaterializeCause.CHECKPOINT)
    derive(a_week(), cause=MaterializeCause.SOLVE_FAILED)

    assert {cause: _counted(cause) - before[cause] for cause in MaterializeCause} == {
        MaterializeCause.PHASE1: 0,
        MaterializeCause.CHECKPOINT: 1,
        MaterializeCause.SOLVE_FAILED: 1,
    }


def test_a_materialization_that_produced_no_document_is_counted_by_nothing() -> None:
    # The count is what tells a degraded plan from an outage, so counting a refusal inverts the one
    # reading the `solve_failed` alert rests on: a fallback that produced nothing IS the outage.
    before = {cause: _counted(cause) for cause in MaterializeCause}

    with pytest.raises(MaterializeError):
        materialize(
            a_week(frame=(_keyed_against_another_week(),)), cause=MaterializeCause.CHECKPOINT
        )

    assert {cause: _counted(cause) for cause in MaterializeCause} == before


def _counted(cause: MaterializeCause) -> float:
    for metric in MATERIALIZE_TOTAL.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels == {"cause": cause.value}:
                return sample.value
    return 0.0


# --------------------------------------------------------------------------------
# What is placed
# --------------------------------------------------------------------------------


def test_a_derived_week_places_the_frame_the_commitments_the_buffers_and_the_entries() -> None:
    document = materialize(a_week(), cause=MaterializeCause.PHASE1)

    assert set(blocks_by_origin(document)) == {
        Origin.FRAME,
        Origin.ANCHOR,
        Origin.TRANSIT,
        Origin.PREP,
        Origin.TEMPLATE_ENTRY,
    }
    assert len(document.blocks) == 5


def test_no_content_is_bound_so_no_habit_or_task_block_appears() -> None:
    # Bounded by the inventory of what a document may hold rather than by naming what is absent: a
    # habit occurrence or a task chunk reaching a derived week is content nobody chose.
    document = materialize(a_week(), cause=MaterializeCause.PHASE1)

    assert {block.binding.kind for block in document.blocks} == {
        BindingKind.ROUTINE,
        BindingKind.ANCHOR,
        BindingKind.ANCHOR_TRANSIT,
        BindingKind.ANCHOR_PREP,
        BindingKind.TEMPLATE_ENTRY,
    }


def test_the_frame_is_placed_at_the_duration_it_arrived_at_and_is_not_resized() -> None:
    # The frame defines the space rather than competing inside it, so a routine reduced by an
    # approved concession arrives short and stays short. Nothing here reads its minimum.
    reduced = a_frame_entry(interval=between(23, 29), min_duration_minutes=6 * 60)

    document = materialize(a_week(frame=(reduced,)), cause=MaterializeCause.PHASE1)

    placed = blocks_by_origin(document)[Origin.FRAME][0]
    assert placed.interval == reduced.interval
    assert placed.interval.total_minutes() == 6 * 60


def test_a_commitment_keeps_its_own_time_however_far_it_reaches_past_the_week() -> None:
    # An anchor's duration is its publisher's fact rather than this week's reading of it, so it is
    # neither clipped to the span nor snapped to the grid.
    overrunning = an_anchor(interval=between(23.1, 26.4, day=6), title="Red-eye to Berlin")

    document = materialize(a_week(anchors=(overrunning,)), cause=MaterializeCause.PHASE1)

    assert blocks_by_origin(document)[Origin.ANCHOR][0].interval == overrunning.interval


def test_a_buffer_carries_the_area_its_type_named_and_the_frame_and_a_commitment_carry_none() -> (
    None
):
    document = materialize(a_week(), cause=MaterializeCause.PHASE1)

    charged = {block.origin: block.area_id for block in document.blocks}
    assert charged[Origin.TRANSIT] == CAREER
    assert charged[Origin.PREP] == CAREER
    assert charged[Origin.TEMPLATE_ENTRY] == FITNESS
    assert charged[Origin.FRAME] is None
    assert charged[Origin.ANCHOR] is None


def test_no_block_is_pinned_because_derivation_moved_none_of_them_off_anything() -> None:
    # Fixed by derivation is not the same as pinned. Neither carries a pin glyph obligation the
    # other does: a pin is the user's own edit and a training label, and a derived placement is
    # neither, even though the solver may not move it either.
    document = materialize(a_week(), cause=MaterializeCause.PHASE1)

    assert not any(block.pinned for block in document.blocks)
    assert {block.superseded_placement for block in document.blocks} == {None}


def test_a_forbidden_window_is_emitted_with_its_scope_and_its_forbidden_areas_intact() -> None:
    # The split by scope happens in the probe's projection and nowhere else, so a document carries
    # the window as it arrived: H2 and H13 read one window two ways and each reads its own field.
    scoped = a_recovery_window(
        interval=between(13, 14), scope=ForbiddenScope.AREAS, forbidden_area_ids=(FITNESS,)
    )

    document = materialize(a_week(forbidden_windows=(scoped,)), cause=MaterializeCause.PHASE1)

    assert document.forbidden_windows == (scoped,)
    assert document.forbidden_windows[0].forbidden_area_ids == (FITNESS,)


def test_an_empty_week_materializes_an_empty_document_rather_than_nothing() -> None:
    document = materialize(inputs(), cause=MaterializeCause.CHECKPOINT)

    assert (document.blocks, document.forbidden_windows, document.empty_slots) == ((), (), ())
    assert document.iso_week == WEEK
    assert set(document.zone_by_date) == set(WEEK.dates())


def test_a_title_reaches_the_block_exactly_as_the_publisher_wrote_it() -> None:
    # Bounding and scrubbing text is a boundary concern with one home at the api, so a control
    # character or a zero-width space in an imported title is carried rather than silently
    # rewritten here: a second definition of a text class would diverge from that one.
    hostile = an_anchor(title="Kontron\u0085Interview\u200b ")

    document = materialize(a_week(anchors=(hostile,)), cause=MaterializeCause.PHASE1)

    assert blocks_by_origin(document)[Origin.ANCHOR][0].title == "Kontron\u0085Interview\u200b "


# --------------------------------------------------------------------------------
# Slots
# --------------------------------------------------------------------------------


def test_every_area_slot_becomes_an_empty_slot_stating_that_nothing_is_chosen_yet() -> None:
    document = materialize(a_week(), cause=MaterializeCause.PHASE1)

    assert [(slot.area_id, slot.reason) for slot in document.empty_slots] == [
        (FITNESS, EmptySlotReason.NOT_SOLVED)
    ]


def test_an_unfilled_slot_keeps_its_declared_time_and_duration() -> None:
    # Shrinking it would need a minimum-slot rule and would read as the solver editing the user's
    # template, which template pinning forbids.
    slot = a_slot(interval=between(18, 19.5))

    document = materialize(a_week(template_entries=(slot,)), cause=MaterializeCause.PHASE1)

    assert document.empty_slots[0].interval == slot.interval


def test_the_slot_label_says_the_content_is_unchosen_rather_than_that_the_backlog_is_empty() -> (
    None
):
    # Nobody looked at the backlog, so borrowing the empty-backlog wording would state something
    # no code here computed. One reason, one label, and the two are not interchangeable.
    context = SlotContext(area_name="Fitness")

    document = materialize(a_week(), cause=MaterializeCause.PHASE1)

    label = document.empty_slots[0].gutter_label(context)
    assert label == "content not yet chosen"
    assert label != gutter_label(EmptySlotReason.NO_ELIGIBLE_CONTENT, context)


def test_a_slot_is_emitted_even_where_a_commitment_already_holds_the_time() -> None:
    # A slot reports what was computed about its content, and nothing was: whether the span is
    # placeable is the question a solve answers, and answering it here would report a constraint
    # nobody evaluated.
    document = materialize(
        a_week(template_entries=(a_slot(interval=between(10, 11)),)), cause=MaterializeCause.PHASE1
    )

    assert len(document.empty_slots) == 1
    assert document.empty_slots[0].reason is EmptySlotReason.NOT_SOLVED


# --------------------------------------------------------------------------------
# The reason record
# --------------------------------------------------------------------------------


def test_every_block_carries_exactly_one_clause_and_it_is_a_bound_clause() -> None:
    # B3 with no exception carved out for a derived plan. Five of the six clause kinds have
    # nothing to draw on here, so `bound` widened to name a derivation is what keeps the vocabulary
    # closed at six and `Block.reason` non-optional.
    document = materialize(a_week(), cause=MaterializeCause.PHASE1)

    assert document.blocks
    for block in document.blocks:
        assert isinstance(only_clause(block), Bound), block.title


def test_each_kind_of_derived_block_names_the_kind_of_determinant_that_fixed_it() -> None:
    document = materialize(a_week(), cause=MaterializeCause.PHASE1)

    assert {block.origin: bound_clause(block).source for block in document.blocks} == {
        Origin.FRAME: DerivationSource.ROUTINE,
        Origin.TEMPLATE_ENTRY: DerivationSource.TEMPLATE_ENTRY,
        Origin.ANCHOR: DerivationSource.ANCHOR,
        Origin.TRANSIT: DerivationSource.ANCHOR_TYPE,
        Origin.PREP: DerivationSource.ANCHOR_TYPE,
    }


def test_each_bound_clause_renders_the_determinant_and_the_geometry_it_was_derived_at() -> None:
    # Four fragments of the upstream examples are absent from these rows, and each is absent
    # because no resolved input carries it: the day type a shape belongs to, a routine's day-type
    # association, which cannot exist because a routine materializes on every date, the calendar
    # and access role a commitment was read from, and the anchor type's own name together with the
    # title of the commitment that cast a buffer, which is reachable only through a join that is
    # not total. Each row therefore names its determinant and the geometry, and never a value that
    # depends on whether an unrelated collection happens to carry a row.
    anchor = an_anchor(interval=between(10, 11), title="Kontron Placement Interview")
    week = a_week(
        anchors=(anchor,),
        frame=(a_frame_entry(interval=between(23, 31), title="Sleep"),),
        shadow_blocks=(
            a_transit_block(
                anchor_id=anchor.anchor_id, interval=between(9.5, 10), title="Leave for Uni"
            ),
        ),
        template_entries=(a_concrete_entry(interval=between(6.75, 7), title="Shower"),),
    )

    document = materialize(week, cause=MaterializeCause.PHASE1)

    assert {rendered(bound_clause(block)) for block in document.blocks} == {
        "routine · Sleep · 23:00 + 8h",
        "template_entry · Shower · 06:45",
        "anchor_type · Leave for Uni · transit out, 30m",
        "anchor · Kontron Placement Interview",
    }


def test_a_prep_buffer_and_the_two_transit_legs_each_say_which_buffer_they_are() -> None:
    # The one discriminator between `Leave for Uni` and `Go Home`, read back through the closed
    # vocabulary that defines it rather than described a second time.
    anchor = an_anchor(interval=between(10, 11))
    week = a_week(
        shadow_blocks=(
            a_prep_block(
                anchor_id=anchor.anchor_id, interval=between(8, 9), title="Interview prep"
            ),
            a_transit_block(
                anchor_id=anchor.anchor_id,
                leg=TransitLeg.OUT,
                interval=between(9.5, 10),
                title="Leave for Uni",
            ),
            a_transit_block(
                anchor_id=anchor.anchor_id,
                leg=TransitLeg.BACK,
                interval=between(11, 11.25),
                title="Go Home",
            ),
        ),
        anchors=(anchor,),
        forbidden_windows=(),
    )

    document = materialize(week, cause=MaterializeCause.PHASE1)

    assert {rendered(bound_clause(block)) for block in document.blocks if block.area_id} == {
        "anchor_type · Interview prep · prep, 1h",
        "anchor_type · Leave for Uni · transit out, 30m",
        "anchor_type · Go Home · transit back, 15m",
        "template_entry · Shower · 06:45",
    }


def test_an_hour_and_a_half_reads_as_hours_and_minutes_rather_than_as_ninety() -> None:
    week = a_week(frame=(a_frame_entry(interval=between(23, 24.5)),), template_entries=())

    document = materialize(week, cause=MaterializeCause.PHASE1)

    frame = blocks_by_origin(document)[Origin.FRAME][0]
    assert bound_clause(frame).selected.endswith("23:00 + 1h30m")


def test_a_wall_time_is_rendered_in_the_zone_the_occurrence_was_resolved_in() -> None:
    # The clause says what the user declared, so a week whose days sit in two zones reports each
    # occurrence at the time its own day was declared for rather than at one shared offset.
    travelling = dict(zones())
    travelling[on(0)] = "Asia/Tokyo"

    document = materialize(
        a_week(zone_by_date=travelling, frame=(a_frame_entry(interval=between(23, 31)),)),
        cause=MaterializeCause.PHASE1,
    )

    assert bound_clause(blocks_by_origin(document)[Origin.FRAME][0]).selected == (
        "Sleep · 08:00 + 8h"
    )


def test_an_occurrence_keyed_against_another_week_is_refused_rather_than_read_against_a_zone() -> (
    None
):
    # Which week owns an occurrence is the producer's question. Answering it here, by reading a
    # neighbouring day's zone, would hide a producer that answered it wrongly.
    with pytest.raises(MaterializeError, match="names no date of this week"):
        materialize(a_week(frame=(_keyed_against_another_week(),)), cause=MaterializeCause.PHASE1)


def _keyed_against_another_week() -> FrameEntry:
    """A frame occurrence keyed by a date this week does not hold, which no producer emits."""
    return FrameEntry(
        routine_id=an_anchor().anchor_id,
        occurrence_key="2026-03-01",
        interval=between(23, 31),
        min_duration_minutes=60,
        flex_band_minutes=0,
        title="Sleep",
    )


# --------------------------------------------------------------------------------
# Identity, and the overlap rule
# --------------------------------------------------------------------------------


def test_every_block_id_is_the_derivation_of_the_week_and_the_binding() -> None:
    # B6. There is no field to set and no argument to pass, so the id cannot drift from the content
    # it names, and two documents pair on it with no lookup of any kind.
    document = materialize(a_week(), cause=MaterializeCause.PHASE1)

    assert {block.id for block in document.blocks} == {
        block_id(WEEK, block.binding) for block in document.blocks
    }
    assert len(document.blocks_by_id()) == len(document.blocks)


def test_one_binding_per_date_gives_a_week_of_entries_seven_identities() -> None:
    week = a_week(
        template_entries=tuple(
            a_concrete_entry(day=day, interval=between(12, 12.5, day=day)) for day in range(7)
        )
    )

    document = materialize(week, cause=MaterializeCause.PHASE1)

    entries = blocks_by_origin(document)[Origin.TEMPLATE_ENTRY]
    assert len({block.id for block in entries}) == 7


def test_a_candidate_over_a_commitment_is_refused_and_the_refusal_names_the_rule() -> None:
    # H4 is what this protects: derivation never creates an overlap of its own. A concrete entry
    # over a commitment is the conflict TE3 hands to the user, so it is not placed and the reason
    # travels rather than being reconstructed later.
    anchor = an_anchor(interval=between(10, 11), title="Kontron Placement Interview")
    colliding = a_concrete_entry(interval=between(10.5, 10.75), title="Shower")

    materialized = derive(
        a_week(anchors=(anchor,), template_entries=(colliding,), shadow_blocks=()),
        cause=MaterializeCause.PHASE1,
    )

    assert [block.origin for block in materialized.document.blocks] == [
        Origin.ANCHOR,
        Origin.FRAME,
    ]
    assert [
        (rejection.rule, rejection.window, rejection.detail) for rejection in materialized.blocked
    ] == [
        (
            ConstraintRule.ANCHOR_OVERLAP,
            colliding.interval,
            "Kontron Placement Interview",
        )
    ]


def test_a_candidate_over_a_block_that_has_begun_is_refused_by_the_span_the_week_spent() -> None:
    # Derivation is the caller that seeds nothing: it places what nothing had to choose, and it
    # honours no pin and carries no past block. So the spans the week has already spent reach the
    # occupancy rules through the state's own indexes, and an entry over one of them is refused
    # rather than placed on top of time that has gone.
    gym = BindingRef.for_task(UUID(int=61))
    began = a_block(binding=gym, interval=between(8.5, 9.5), title="Gym")
    colliding = a_concrete_entry(interval=between(9, 9.25), title="Shower")

    materialized = derive(
        a_week(
            live_plan=a_live_plan(began),
            shadow_blocks=(),
            template_entries=(colliding,),
        ),
        cause=MaterializeCause.PHASE1,
    )

    assert [
        (rejection.rule, rejection.window, rejection.detail) for rejection in materialized.blocked
    ] == [(ConstraintRule.BLOCK_OVERLAP, colliding.interval, "Gym")]
    assert [block.origin for block in materialized.document.blocks] == [
        Origin.ANCHOR,
        Origin.FRAME,
    ]


def test_a_buffer_is_offered_before_an_entry_so_a_collision_costs_the_entry() -> None:
    # A buffer's geometry is cast by an immovable commitment, and an entry is the shape the user
    # declared for the day. Which of the two gives way is stated rather than left to the order the
    # inputs happened to arrive in.
    anchor = an_anchor(interval=between(10, 11))
    buffer = a_transit_block(anchor_id=anchor.anchor_id, interval=between(9.5, 10))
    entry = a_concrete_entry(interval=between(9.75, 10))

    materialized = derive(
        a_week(anchors=(anchor,), shadow_blocks=(buffer,), template_entries=(entry,)),
        cause=MaterializeCause.PHASE1,
    )

    assert {block.origin for block in materialized.document.blocks} >= {Origin.TRANSIT}
    assert [rejection.binding for rejection in materialized.blocked] == [
        _entry_binding(materialized, entry.entry_id)
    ]


def test_two_frame_occurrences_of_one_night_are_both_placed() -> None:
    # A routine of more than a local day overlaps its own next occurrence and no duration cap
    # expresses otherwise. Both are emitted: each date keys its own block, so dropping either
    # would lose a key an outcome may already reference, and two frame blocks overlapping is a
    # state the grid draws with no special case.
    saturday = a_frame_entry(day=5, interval=between(23, 31, day=5))
    sunday = a_frame_entry(day=6, interval=between(6, 14, day=6))

    document = materialize(
        a_week(frame=(saturday, sunday), template_entries=()), cause=MaterializeCause.PHASE1
    )

    placed = blocks_by_origin(document)[Origin.FRAME]
    assert len(placed) == 2
    assert placed[0].interval.overlaps(placed[1].interval)


def test_two_commitments_at_one_time_are_both_placed() -> None:
    # A double-booked calendar is a fact about the week rather than a choice a solve made, and the
    # overlap constraint binds the solve rather than the plan.
    first = an_anchor(interval=between(10, 11), title="Kontron Placement Interview")
    second = an_anchor(interval=between(10.5, 11.5), title="Dentist")

    document = materialize(
        a_week(anchors=(first, second), shadow_blocks=(), template_entries=()),
        cause=MaterializeCause.PHASE1,
    )

    assert {block.title for block in document.blocks if block.origin is Origin.ANCHOR} == {
        "Kontron Placement Interview",
        "Dentist",
    }


def test_nothing_derivation_chose_to_place_overlaps_anything_else_it_placed() -> None:
    # The half of B4 that binds this function: the frame and the commitments are the space and may
    # overlap each other, and every block placed INSIDE that space is checked against it and
    # against the placements before it.
    anchor = an_anchor(interval=between(10, 11))
    week = a_week(
        anchors=(anchor,),
        shadow_blocks=(
            a_transit_block(anchor_id=anchor.anchor_id, interval=between(9.5, 10)),
            a_transit_block(
                anchor_id=anchor.anchor_id, leg=TransitLeg.BACK, interval=between(9.75, 10.25)
            ),
        ),
        template_entries=(a_concrete_entry(interval=between(9.5, 10)),),
    )

    document = materialize(week, cause=MaterializeCause.PHASE1)

    chosen = [
        block for block in document.blocks if block.origin not in {Origin.FRAME, Origin.ANCHOR}
    ]
    assert len(chosen) == 1
    for one in chosen:
        assert not any(
            one.interval.overlaps(other.interval) for other in chosen if other.id != one.id
        )


def test_a_buffer_is_refused_inside_another_commitments_window_forbidding_its_own_area() -> None:
    # A buffer carries an Area, so the span a derived plan may not take is not only the span nothing
    # at all may take: a Career prep block inside a second commitment's recovery window forbidding
    # Career is a placement derivation determined and may not keep. Nothing upstream suppresses it,
    # so this rule is the enforcement rather than a second opinion.
    interview = an_anchor(interval=between(16, 16.75), title="Kontron Placement Interview")
    lecture = an_anchor(interval=between(17.5, 19), title="Lecture")
    recovery = a_recovery_window(
        interval=between(16.75, 18),
        anchor_id=interview.anchor_id,
        scope=ForbiddenScope.AREAS,
        forbidden_area_ids=(CAREER,),
    )
    prep = a_prep_block(anchor_id=lecture.anchor_id, interval=between(17, 17.5), area_id=CAREER)

    materialized = derive(
        a_week(
            anchors=(interview, lecture),
            forbidden_windows=(recovery,),
            shadow_blocks=(prep,),
            template_entries=(),
        ),
        cause=MaterializeCause.PHASE1,
    )

    assert Origin.PREP not in blocks_by_origin(materialized.document)
    assert [(rejection.rule, rejection.detail) for rejection in materialized.blocked] == [
        (ConstraintRule.FORBIDDEN_AREA, recovery.label)
    ]


def test_a_buffer_of_another_area_is_still_placed_inside_the_same_window() -> None:
    # The other half of the same rule, without which it would be H2 under a second name: a Transit
    # block inside a window forbidding Career only is legal, and the gym would be too.
    interview = an_anchor(interval=between(16, 16.75), title="Kontron Placement Interview")
    lecture = an_anchor(interval=between(17.5, 19), title="Lecture")
    recovery = a_recovery_window(
        interval=between(16.75, 18),
        anchor_id=interview.anchor_id,
        scope=ForbiddenScope.AREAS,
        forbidden_area_ids=(CAREER,),
    )
    transit = a_transit_block(
        anchor_id=lecture.anchor_id, interval=between(17, 17.5), area_id=FITNESS
    )

    materialized = derive(
        a_week(
            anchors=(interview, lecture),
            forbidden_windows=(recovery,),
            shadow_blocks=(transit,),
            template_entries=(),
        ),
        cause=MaterializeCause.PHASE1,
    )

    assert Origin.TRANSIT in blocks_by_origin(materialized.document)
    assert materialized.blocked == ()


def test_the_journey_home_a_commitment_casts_is_placed_inside_its_own_recovery_window() -> None:
    # Recovery runs from the commitment's end and so does the return leg, so `Go Home` sits inside
    # recovery by construction. Without the exemption the one block a lecture reliably casts would
    # be refused by every derivation.
    lecture = an_anchor(interval=between(16, 17.5), title="Lecture")
    recovery = a_recovery_window(
        interval=between(17.5, 18.75), anchor_id=lecture.anchor_id, label="recovery · Lecture"
    )
    going_home = a_transit_block(
        anchor_id=lecture.anchor_id,
        leg=TransitLeg.BACK,
        interval=between(17.5, 18),
        title="Go Home",
    )

    materialized = derive(
        a_week(
            anchors=(lecture,),
            forbidden_windows=(recovery,),
            shadow_blocks=(going_home,),
            template_entries=(),
        ),
        cause=MaterializeCause.PHASE1,
    )

    assert [block.title for block in blocks_by_origin(materialized.document)[Origin.TRANSIT]] == [
        "Go Home"
    ]
    assert materialized.blocked == ()


# --------------------------------------------------------------------------------
# The contract a solve inherits
# --------------------------------------------------------------------------------


def fixed_elements(document: PlanDocument) -> tuple[object, ...]:
    """The parts of a week content binding may not move, as a value two documents can compare.

    This is the contract phase 1 owns. A solve of the same inputs runs the same phase, so its
    document holds these unchanged, and the half of that assertion which needs a solve to exist
    lands with the solve.
    """
    return (
        tuple(
            (block.id, block.interval, block.title, block.reason)
            for block in document.blocks
            if block.origin in DERIVED_ORIGINS
        ),
        document.forbidden_windows,
        tuple(document.zone_by_date.items()),
    )


def test_the_fixed_elements_of_a_week_are_the_frame_the_commitments_and_the_buffers() -> None:
    document = materialize(a_week(), cause=MaterializeCause.PHASE1)

    derived, windows, zone_by_date = fixed_elements(document)
    assert {origin for origin in blocks_by_origin(document) if origin in DERIVED_ORIGINS} == {
        Origin.FRAME,
        Origin.ANCHOR,
        Origin.TRANSIT,
        Origin.PREP,
    }
    assert len(derived) == 4  # type: ignore[arg-type]
    assert windows == document.forbidden_windows
    assert zone_by_date == tuple(document.zone_by_date.items())


def test_the_fixed_elements_are_the_same_whichever_cause_asked_for_them() -> None:
    # The contract a solve is held to, asserted here against the only caller that exists: the label
    # a caller passes changes a counter and nothing about the week. When the search phases land they
    # run this same phase first, and their document is compared with this reading rather than with a
    # second definition of it.
    week = a_week()

    assert fixed_elements(materialize(week, cause=MaterializeCause.PHASE1)) == fixed_elements(
        materialize(week, cause=MaterializeCause.CHECKPOINT)
    )


def _entry_binding(materialized: Materialization, entry_id: UUID) -> BindingRef:
    """The binding a refused template entry carried, read from the refusal itself."""
    return next(
        rejection.binding
        for rejection in materialized.blocked
        if rejection.binding.entity_id == entry_id
    )
