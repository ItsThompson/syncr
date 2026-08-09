"""The plan document: what a block may be, what a week may hold, and what a diff sees.

Four groups.

**A block derives three values rather than storing them.** Its id, its origin, and its chunk
number are read from the week and the binding, so there is no field for any of them and no
argument to pass. The structural assertions are the point: a rule enforced by the absence of a
field cannot be broken by a caller.

**The block invariants, in both directions.** B2 is asserted per origin and per direction,
including that prep and transit DO carry an Area, which is the half a reader is most likely to
get wrong. B1 is asserted both ways, because a superseded placement without a pin would render
a counterfactual nobody chose.

**A document holds one week, once each.** Two blocks of one binding would make the pairing a
diff performs ambiguous, and a block from another week carries an id derived against that week.

**What a diff sees, which is why the keys are what they are.** A week-pattern edit does not
re-key a dated occurrence, and a habit moved from Monday to Wednesday reads as one binding with
a changed interval rather than as a removal plus an addition. Both are asserted by pairing two
documents on their ids, with no lookup of any kind.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, NamedTuple
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from syncr_domain.discretionary import OccupancyKind, is_subtracted
from syncr_domain.gaps import EmptySlotReason
from syncr_domain.identity import BindingKind, BindingRef, Origin, TransitLeg, block_id
from syncr_domain.plan import MIN_SPLIT_COUNT, Block, PlanDocument, PlanError, RevisionReason
from syncr_domain.reasons import ReasonError
from syncr_domain.weeks import IsoWeek
from tests.plan_values import (
    CAREER,
    INTERVIEW,
    ORIGINS_WITHOUT_AN_AREA,
    WEEK,
    a_binding,
    a_block,
    a_block_of,
    a_document,
    a_slot,
    a_window,
    a_zone_map,
    between,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from syncr_domain.identity import BlockId
    from syncr_domain.intervals import Interval

SHOWER_ENTRY = uuid4()
GYM = uuid4()
LEETCODE = uuid4()

MORNING = between(6, 7.5)
AFTERNOON = between(13, 14.5)

ORIGINS_WITH_AN_AREA = [
    Origin.TEMPLATE_ENTRY,
    Origin.HABIT,
    Origin.TASK,
    Origin.PREP,
    Origin.TRANSIT,
]

# Which kind of span the denominator reads a block of each origin as. The mapping in `plan.py`
# is the statement of record and this is the expectation it is measured against, so a block
# routed to the wrong kind fails a case of its own rather than passing a membership test that
# the property's return type already guarantees.
OCCUPANCY_BY_ORIGIN = {
    Origin.FRAME: OccupancyKind.FRAME,
    Origin.ANCHOR: OccupancyKind.ANCHOR,
    Origin.PREP: OccupancyKind.PREP_BLOCK,
    Origin.TRANSIT: OccupancyKind.TRANSIT_BLOCK,
    Origin.TASK: OccupancyKind.TASK_BLOCK,
    Origin.HABIT: OccupancyKind.HABIT_BLOCK,
    Origin.TEMPLATE_ENTRY: OccupancyKind.TEMPLATE_ENTRY_BLOCK,
}


class Diff(NamedTuple):
    """What pairing two documents on their block ids produces. The classifier's own shape."""

    added: frozenset[BlockId]
    removed: frozenset[BlockId]
    moved: frozenset[BlockId]


def diff(live: PlanDocument, candidate: PlanDocument) -> Diff:
    """Pair two documents on their derived ids.

    Written here rather than imported, because the classifier is not this module's. What it
    demonstrates is that pairing needs nothing but the two documents.
    """
    before, after = live.blocks_by_id(), candidate.blocks_by_id()
    return Diff(
        added=frozenset(after) - frozenset(before),
        removed=frozenset(before) - frozenset(after),
        moved=frozenset(
            block_id
            for block_id in frozenset(before) & frozenset(after)
            if before[block_id].interval != after[block_id].interval
        ),
    )


def a_week_of(bindings: Iterable[BindingRef]) -> PlanDocument:
    """One week holding one block per binding, each with the Area its origin requires."""
    return a_document(
        blocks=tuple(
            a_block(
                binding=binding,
                interval=MORNING,
                area_id=None if binding.origin in ORIGINS_WITHOUT_AN_AREA else CAREER,
            )
            for binding in bindings
        )
    )


@st.composite
def a_week_and_a_permutation(draw: st.DrawFn) -> tuple[list[BindingRef], list[BindingRef]]:
    """A week's bindings and the same bindings in a generated order."""
    kinds = draw(st.lists(st.sampled_from(list(BindingKind)), min_size=1, max_size=7, unique=True))
    bindings = [a_binding(kind) for kind in kinds]
    return bindings, draw(st.permutations(bindings))


class TestABlockDerivesRatherThanStores:
    def test_a_block_has_no_id_field_to_supply(self) -> None:
        """I1, structurally. An id that cannot be passed cannot be passed wrongly."""
        from dataclasses import fields

        assert "id" not in {field.name for field in fields(Block)}

    def test_a_block_id_is_the_derivation_over_its_own_week_and_binding(self) -> None:
        """B6. The equality the authority classifier's whole no-lookup property rests on."""
        binding = a_binding()
        block = a_block(binding=binding)

        assert block.id == block_id(WEEK, binding)

    def test_two_blocks_of_one_binding_in_one_week_share_an_id(self) -> None:
        """Whatever else differs. This is what makes a re-solve's output pair with the live plan."""
        binding = a_binding()
        planned = a_block(binding=binding, interval=MORNING, title="Gym · Legs")
        moved = a_block(
            binding=binding,
            interval=AFTERNOON,
            title="Gym · Cardio",
            pinned=True,
            superseded_placement=MORNING,
            objective_delta=4.25,
        )

        assert planned.id == moved.id

    def test_a_block_has_no_origin_field_either(self) -> None:
        """The two vocabularies map bijectively, so storing both would let them disagree."""
        from dataclasses import fields

        assert "origin" not in {field.name for field in fields(Block)}

    @pytest.mark.parametrize("origin", list(Origin), ids=[origin.value for origin in Origin])
    def test_a_block_reads_its_origin_from_its_binding(self, origin: Origin) -> None:
        assert a_block_of(origin).origin is origin

    def test_a_block_reads_its_chunk_number_from_the_binding_the_id_uses(self) -> None:
        binding = BindingRef.for_task(LEETCODE, split_index=1)
        block = a_block(binding=binding, split_count=3)

        assert block.split_index == 1
        assert block.id == block_id(WEEK, binding)

    def test_an_undivided_block_has_no_chunk_number(self) -> None:
        assert a_block().split_index is None

    def test_a_block_with_no_title_names_nothing(self) -> None:
        """A block's title is the resolved content name, which is what the grid renders."""
        with pytest.raises(PlanError, match="names nothing"):
            a_block(title="")

    def test_a_title_of_whitespace_is_not_judged_here(self) -> None:
        """Characterization, deliberately, and the same answer a window's label gets.

        What counts as whitespace and what counts as unreadable is one class with one
        definition, and it lives at the boundary that fits publisher text to a column. A second
        definition here would diverge from that one the first time either changed.
        """
        assert a_block(title=" ").title == " "


class TestWhichBlocksCarryAnArea:
    @pytest.mark.parametrize(
        "origin", ORIGINS_WITH_AN_AREA, ids=[origin.value for origin in ORIGINS_WITH_AN_AREA]
    )
    def test_every_origin_but_the_frame_and_an_anchor_carries_one(self, origin: Origin) -> None:
        """B2's other half, including prep and transit: both consume their Area's time."""
        assert a_block_of(origin).area_id == CAREER

    @pytest.mark.parametrize(
        "origin", ORIGINS_WITH_AN_AREA, ids=[origin.value for origin in ORIGINS_WITH_AN_AREA]
    )
    def test_one_of_them_without_an_area_is_refused(self, origin: Origin) -> None:
        with pytest.raises(PlanError, match="carries an Area"):
            a_block_of(origin, area_id=None)

    @pytest.mark.parametrize("origin", [Origin.FRAME, Origin.ANCHOR], ids=["frame", "anchor"])
    def test_the_frame_and_an_anchor_carry_none(self, origin: Origin) -> None:
        assert a_block_of(origin).area_id is None

    @pytest.mark.parametrize("origin", [Origin.FRAME, Origin.ANCHOR], ids=["frame", "anchor"])
    def test_either_of_them_with_an_area_is_refused(self, origin: Origin) -> None:
        """A routine is not a category competing with Fitness, and an anchor is not owned."""
        with pytest.raises(PlanError, match="carries no Area"):
            a_block_of(origin, area_id=CAREER)


class TestWhichKindOfSpanABlockIs:
    @pytest.mark.parametrize(
        ("origin", "kind"),
        list(OCCUPANCY_BY_ORIGIN.items()),
        ids=[origin.value for origin in OCCUPANCY_BY_ORIGIN],
    )
    def test_every_origin_names_the_one_kind_the_denominator_reads_it_as(
        self, origin: Origin, kind: OccupancyKind
    ) -> None:
        """Total over the seven, so the assembler converts a block rather than deciding about one.

        Each origin is a case of its own and each states the kind it expects, so an origin the
        mapping stops naming fails alone and names itself, and an origin routed to another
        origin's kind fails as well.
        """
        assert a_block_of(origin).occupancy_kind is kind

    def test_the_pairs_asserted_above_are_every_origin_there_is(self) -> None:
        """The control on that table: an eighth origin fails here until it names its kind."""
        assert set(OCCUPANCY_BY_ORIGIN) == set(Origin)

    def test_the_origins_name_a_different_kind_each(self) -> None:
        """The two vocabularies map bijectively, which is why neither is stored twice.

        Counted off the blocks rather than off the table above, so two origins sharing one kind
        fails here and not only at the pair whose expectation changed.
        """
        kinds = {a_block_of(origin).occupancy_kind for origin in Origin}

        assert len(kinds) == len(Origin)

    def test_a_concrete_entry_is_its_own_kind_rather_than_the_slot_it_is_not(self) -> None:
        """A slot's content is bound late, so a filled slot's block takes the filler's origin."""
        assert (
            a_block_of(Origin.TEMPLATE_ENTRY).occupancy_kind is OccupancyKind.TEMPLATE_ENTRY_BLOCK
        )

    def test_no_block_maps_onto_the_slot_kind(self) -> None:
        """The control on the pair above: a slot describes a slot, and blocks are not slots."""
        kinds = {a_block_of(origin).occupancy_kind for origin in Origin}

        assert OccupancyKind.SLOT_BLOCK not in kinds

    @pytest.mark.parametrize(
        "origin", ORIGINS_WITH_AN_AREA, ids=[origin.value for origin in ORIGINS_WITH_AN_AREA]
    )
    def test_a_block_carrying_an_area_stays_in_the_denominator(self, origin: Origin) -> None:
        """B2 and the subtraction table agree: allocation to an Area is not removal.

        The crossing is what makes the new member a vocabulary completion rather than an
        arithmetic change. A concrete entry behaved this way already, by not being named at all.
        """
        assert is_subtracted(a_block_of(origin).occupancy_kind) is False

    @pytest.mark.parametrize("origin", [Origin.FRAME, Origin.ANCHOR], ids=["frame", "anchor"])
    def test_a_block_carrying_no_area_leaves_it(self, origin: Origin) -> None:
        assert is_subtracted(a_block_of(origin).occupancy_kind) is True


class TestWhatAPinHasToState:
    def test_a_pin_states_the_placement_it_replaced_and_what_that_cost(self) -> None:
        block = a_block(
            interval=AFTERNOON, pinned=True, superseded_placement=MORNING, objective_delta=4.25
        )

        assert (block.superseded_placement, block.objective_delta) == (MORNING, 4.25)

    @pytest.mark.parametrize(
        ("superseded_placement", "objective_delta"),
        [(None, None), (MORNING, None), (None, 4.25)],
        ids=["neither", "no cost", "no placement"],
    )
    def test_a_pin_without_both_is_refused(
        self, superseded_placement: Interval | None, objective_delta: float | None
    ) -> None:
        """B1. The panel renders both from the block rather than by walking the edit log."""
        with pytest.raises(PlanError, match="states the placement it replaced"):
            a_block(
                pinned=True,
                superseded_placement=superseded_placement,
                objective_delta=objective_delta,
            )

    @pytest.mark.parametrize(
        ("superseded_placement", "objective_delta"),
        [(MORNING, None), (None, 4.25), (MORNING, 4.25)],
        ids=["a placement", "a cost", "both"],
    )
    def test_an_unpinned_block_replaced_nothing(
        self, superseded_placement: Interval | None, objective_delta: float | None
    ) -> None:
        """The other direction, which the spec leaves implicit and the panel depends on.

        A block fixed by derivation was never moved off a placement, so a superseded one here
        would render a choice nobody made.
        """
        with pytest.raises(PlanError, match="only a pinned block"):
            a_block(
                pinned=False,
                superseded_placement=superseded_placement,
                objective_delta=objective_delta,
            )

    def test_a_derived_block_may_be_pinned_somewhere_else(self) -> None:
        """Fixed by derivation and pinned by the user are different states, not exclusive ones."""
        block = a_block_of(
            Origin.TEMPLATE_ENTRY,
            interval=AFTERNOON,
            pinned=True,
            superseded_placement=MORNING,
            objective_delta=1.0,
        )

        assert block.pinned

    def test_a_pin_that_cost_nothing_is_representable(self) -> None:
        """Rejecting a proposed move pins a block where it already was, and that costs zero."""
        block = a_block(pinned=True, superseded_placement=MORNING, objective_delta=0.0)

        assert block.objective_delta == 0.0

    @pytest.mark.parametrize("delta", [float("nan"), float("inf")])
    def test_a_pin_cost_a_finite_number_of_objective_units(self, delta: float) -> None:
        """One statement of the rule, read by the block and by the clause that renders it."""
        with pytest.raises(ReasonError, match="finite number"):
            a_block(pinned=True, superseded_placement=MORNING, objective_delta=delta)


class TestWhatAChunkStates:
    def test_a_chunk_states_which_of_how_many(self) -> None:
        block = a_block(binding=BindingRef.for_task(LEETCODE, split_index=2), split_count=3)

        assert (block.split_index, block.split_count) == (2, 3)

    def test_a_chunk_with_no_count_renders_half_a_label(self) -> None:
        with pytest.raises(PlanError, match="no count"):
            a_block(binding=BindingRef.for_task(LEETCODE, split_index=2))

    def test_a_count_with_no_chunk_is_refused_too(self) -> None:
        with pytest.raises(PlanError, match="no index"):
            a_block(binding=BindingRef.for_task(LEETCODE), split_count=3)

    def test_one_chunk_is_the_whole_task(self) -> None:
        with pytest.raises(PlanError, match=f"at least {MIN_SPLIT_COUNT} chunks"):
            a_block(binding=BindingRef.for_task(LEETCODE, split_index=0), split_count=1)

    @pytest.mark.parametrize("split_index", [3, 4], ids=["one past the last", "two past"])
    def test_a_chunk_past_the_count_does_not_exist(self, split_index: int) -> None:
        with pytest.raises(PlanError, match="does not exist"):
            a_block(binding=BindingRef.for_task(LEETCODE, split_index=split_index), split_count=3)

    def test_the_last_chunk_is_one_below_the_count(self) -> None:
        block = a_block(binding=BindingRef.for_task(LEETCODE, split_index=2), split_count=3)

        assert block.split_count == 3
        assert block.split_index == block.split_count - 1


class TestWhatADocumentHolds:
    def test_a_week_with_one_block_of_each_kind_is_a_document(self) -> None:
        document = a_document(
            blocks=tuple(a_block_of(origin) for origin in Origin),
            forbidden_windows=(a_window(),),
            empty_slots=(a_slot(),),
        )

        assert len(document.blocks) == len(Origin)
        assert len(document.blocks_by_id()) == len(Origin)

    def test_an_empty_week_is_a_document(self) -> None:
        """The maintainer brings weeks into the horizon before anything is placed in them."""
        document = a_document(blocks=(), discretionary_minutes=6000, unallocated_minutes=6000)

        assert document.blocks == ()

    def test_a_block_from_another_week_names_nothing_here(self) -> None:
        with pytest.raises(PlanError, match="holds blocks of 2026-W08"):
            a_document(blocks=(a_block(iso_week=IsoWeek(2026, 8)),))

    def test_two_blocks_of_one_binding_cannot_both_be_in_a_week(self) -> None:
        """A diff would pair the first and never see the second."""
        binding = a_binding()

        with pytest.raises(PlanError, match="two blocks share the identity"):
            a_document(
                blocks=(
                    a_block(binding=binding, interval=MORNING),
                    a_block(binding=binding, interval=AFTERNOON),
                )
            )

    def test_seven_nights_of_sleep_are_seven_blocks(self) -> None:
        """The collision the occurrence key exists to prevent, asserted at the document."""
        nights = a_week_of(
            BindingRef.for_routine(uuid4(), on=WEEK.monday() + timedelta(days=offset))
            for offset in range(7)
        )

        assert len(nights.blocks_by_id()) == 7

    def test_a_list_of_blocks_is_held_as_a_tuple(self) -> None:
        blocks = [a_block()]
        document = a_document(blocks=blocks)
        blocks.clear()

        assert len(document.blocks) == 1

    def test_the_zone_map_is_copied_out_of_the_callers_dict(self) -> None:
        """Frozen protects the field, not the mapping the caller passed in."""
        zones = a_zone_map()
        document = a_document(zone_by_date=zones)
        zones.clear()

        assert len(document.zone_by_date) == 7


class TestTheDocumentStatesAZoneForEveryDay:
    def test_all_seven_dates_are_stated(self) -> None:
        assert set(a_document().zone_by_date) == set(WEEK.dates())

    def test_a_missing_day_is_refused_and_named(self) -> None:
        """A day with no zone is a day whose wall times resolve against nothing."""
        partial = a_zone_map()
        del partial[date(2026, 2, 11)]

        with pytest.raises(PlanError, match="leaves out 2026-02-11"):
            a_document(zone_by_date=partial)

    def test_a_day_from_another_week_is_refused_and_named(self) -> None:
        extra = a_zone_map() | {date(2026, 2, 16): "Europe/London"}

        with pytest.raises(PlanError, match="names 2026-02-16"):
            a_document(zone_by_date=extra)

    def test_a_travel_override_mid_week_is_expressible(self) -> None:
        """Which is the reason the map is per date rather than one zone for the week."""
        travelling = a_zone_map() | {
            date(2026, 2, 12): "Pacific/Auckland",
            date(2026, 2, 13): "Pacific/Auckland",
        }
        document = a_document(zone_by_date=travelling)

        assert document.zone_by_date[date(2026, 2, 12)] == "Pacific/Auckland"


class TestTheFigures:
    @pytest.mark.parametrize(
        ("figure", "value"),
        [
            ("discretionary_minutes", -1),
            ("unallocated_minutes", -1),
            ("oversubscription_minutes", -1),
        ],
        ids=["discretionary", "unallocated", "oversubscription"],
    )
    def test_a_figure_that_counts_minutes_is_never_negative(self, figure: str, value: int) -> None:
        """B8, and the two figures beside it that count the same way."""
        with pytest.raises(PlanError, match="none of these is negative"):
            a_document(**{figure: value})

    def test_zero_of_everything_is_a_week(self) -> None:
        """A wholly off-plan week has no discretionary time and nothing unallocated in it."""
        document = a_document(
            blocks=(),
            discretionary_minutes=0,
            unallocated_minutes=0,
            oversubscription_minutes=0,
        )

        assert document.discretionary_minutes == 0

    def test_unallocated_time_is_part_of_discretionary_time(self) -> None:
        with pytest.raises(PlanError, match="is more than the"):
            a_document(discretionary_minutes=100, unallocated_minutes=101)

    def test_a_week_nothing_was_placed_in_is_wholly_unallocated(self) -> None:
        document = a_document(blocks=(), discretionary_minutes=6000, unallocated_minutes=6000)

        assert document.unallocated_minutes == document.discretionary_minutes

    def test_oversubscription_may_exceed_the_time_available(self) -> None:
        """Percentages may sum past 100, and that figure is reported rather than prevented."""
        document = a_document(
            discretionary_minutes=100, unallocated_minutes=0, oversubscription_minutes=400
        )

        assert document.oversubscription_minutes == 400


class TestWhatADiffSees:
    def test_permuting_the_blocks_changes_no_id(self) -> None:
        bindings = [a_binding(kind) for kind in BindingKind]
        forwards = a_week_of(bindings)
        backwards = a_week_of(reversed(bindings))

        assert set(forwards.blocks_by_id()) == set(backwards.blocks_by_id())

    @given(week=a_week_and_a_permutation())
    def test_no_order_of_any_week_changes_its_ids(
        self, week: tuple[list[BindingRef], list[BindingRef]]
    ) -> None:
        """Over generated weeks and generated orders, not only over the reverse of one week."""
        bindings, permuted = week

        assert set(a_week_of(bindings).blocks_by_id()) == set(a_week_of(permuted).blocks_by_id())

    def test_permuting_the_blocks_changes_no_diff(self) -> None:
        bindings = [a_binding(kind) for kind in BindingKind]

        assert diff(a_week_of(bindings), a_week_of(reversed(bindings))) == Diff(
            frozenset(), frozenset(), frozenset()
        )

    def test_a_habit_moved_to_another_day_reads_as_one_binding_that_moved(self) -> None:
        """Not as a removal plus an addition, which is what a date key would have made it.

        A move is what the user did, and a move is what the learning layer trains on.
        """
        binding = BindingRef.for_habit(GYM, index=0)
        monday = a_document(blocks=(a_block(binding=binding, interval=MORNING),))
        wednesday = a_document(blocks=(a_block(binding=binding, interval=between(6, 7.5, day=2)),))

        assert diff(monday, wednesday) == Diff(
            added=frozenset(), removed=frozenset(), moved=frozenset({binding_id(binding)})
        )

    def test_a_week_pattern_edit_does_not_re_key_a_dated_occurrence(self) -> None:
        """Thursday's ``Shower`` keeps its identity when Wednesday stops being a weekday.

        Keyed by position, dropping Wednesday's occurrence would renumber Thursday's from the
        third to the second, so an outcome already recorded against the third would silently
        name a different day.
        """
        weekdays = [WEEK.monday() + timedelta(days=offset) for offset in range(5)]
        before = a_week_of(BindingRef.for_template_entry(SHOWER_ENTRY, on=day) for day in weekdays)
        after = a_week_of(
            BindingRef.for_template_entry(SHOWER_ENTRY, on=day)
            for day in weekdays
            if day.weekday() != 2
        )

        thursday = binding_id(BindingRef.for_template_entry(SHOWER_ENTRY, on=weekdays[3]))
        wednesday = binding_id(BindingRef.for_template_entry(SHOWER_ENTRY, on=weekdays[2]))
        changed = diff(before, after)

        assert changed.removed == frozenset({wednesday})
        assert changed.moved == frozenset()
        assert thursday in after.blocks_by_id()

    def test_reducing_a_cadence_drops_the_last_occurrence_and_re_keys_none(self) -> None:
        four = a_week_of(BindingRef.for_habit(GYM, index=index) for index in range(4))
        three = a_week_of(BindingRef.for_habit(GYM, index=index) for index in range(3))
        changed = diff(four, three)

        assert changed.removed == frozenset({binding_id(BindingRef.for_habit(GYM, index=3))})
        assert changed.added == frozenset()
        assert changed.moved == frozenset()

    def test_an_anchors_two_journeys_diff_separately(self) -> None:
        out = BindingRef.for_anchor_transit(INTERVIEW, leg=TransitLeg.OUT)
        back = BindingRef.for_anchor_transit(INTERVIEW, leg=TransitLeg.BACK)
        both = a_week_of([out, back])
        outbound_only = a_week_of([out])

        assert diff(both, outbound_only).removed == frozenset({binding_id(back)})


class TestTheBuildersThemselves:
    """A shared builder that drops what a caller passed is how a test asserts about nothing.

    `a_block`, `a_document`, `a_window` and `a_slot` merge overrides into the real constructor, so
    a typo raises `TypeError` there already. `a_binding` dispatches per kind, so it has to refuse
    what its branch did not forward.
    """

    @pytest.mark.parametrize(
        ("kind", "override"),
        [
            (BindingKind.HABIT, {"on": date(2026, 2, 12)}),
            (BindingKind.ROUTINE, {"index": 3}),
            (BindingKind.ANCHOR, {"leg": TransitLeg.BACK}),
            (BindingKind.TASK, {"on": date(2026, 2, 12)}),
        ],
        ids=[
            "a date on a habit",
            "an index on a routine",
            "a leg on an anchor",
            "a date on a task",
        ],
    )
    def test_a_binding_refuses_an_override_its_kind_does_not_take(
        self, kind: BindingKind, override: dict[str, object]
    ) -> None:
        with pytest.raises(TypeError, match="takes no"):
            a_binding(kind, **override)

    @pytest.mark.parametrize(
        ("kind", "override", "expected"),
        [
            (BindingKind.ROUTINE, {"on": date(2026, 2, 12)}, "2026-02-12"),
            (BindingKind.TEMPLATE_ENTRY, {"on": date(2026, 2, 12)}, "2026-02-12"),
            (BindingKind.HABIT, {"index": 3}, "03"),
            (BindingKind.ANCHOR_TRANSIT, {"leg": TransitLeg.BACK}, "back"),
        ],
        ids=["a routine's date", "an entry's date", "a habit's index", "a transit leg"],
    )
    def test_the_override_each_kind_does_take_reaches_the_key(
        self, kind: BindingKind, override: dict[str, object], expected: str
    ) -> None:
        assert a_binding(kind, **override).occurrence_key == expected


class TestWhyARevisionExists:
    def test_the_six_reasons_a_row_is_appended(self) -> None:
        assert [reason.value for reason in RevisionReason] == [
            "auto_applied_fill",
            "user_approved",
            "tradeoff_approved",
            "anchor_delta",
            "materialized",
            "horizon_advanced",
        ]

    def test_a_materialized_week_states_a_reason_of_its_own(self) -> None:
        """It is the template-driven plan before any solving, not an approval and not a fill."""
        assert RevisionReason("materialized") is RevisionReason.MATERIALIZED

    def test_an_empty_slot_reason_is_not_a_revision_reason(self) -> None:
        """Two vocabularies about two subjects: why a row exists, and why a slot is empty."""
        assert not {reason.value for reason in RevisionReason} & {
            reason.value for reason in EmptySlotReason
        }


def binding_id(binding: BindingRef) -> BlockId:
    return block_id(WEEK, binding)
