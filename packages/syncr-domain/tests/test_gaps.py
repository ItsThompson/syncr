"""The two gap types: what each forbids, and the one wording each state renders.

Three groups.

**A window says what it forbids through its scope, never through an empty list.** The rule is
one equality, asserted in both directions, because an empty list cannot express the difference
between forbidding nothing and forbidding everything. The two unattributed kinds forbid
everything by construction: they exist because a buffer had no Area, so there is none to scope
them to.

**A window states which kind of span the denominator reads it as, and nothing more.** The
subtraction table has one home in ``discretionary``, so the assertion here is that the mapping
agrees with it rather than a second statement of it.

**Each empty-slot reason renders exactly one label.** They are asserted pairwise distinct over
whatever members exist, and neither ``not_solved`` nor ``elapsed`` may borrow the wording that
claims the backlog was looked at, because nobody looked. The vocabulary's own docstring is
asserted to count nothing, because a count of members goes false the moment one is added.
"""

from __future__ import annotations

import re
from uuid import uuid4

import pytest

from syncr_domain.discretionary import OccupancyKind, is_subtracted
from syncr_domain.gaps import (
    EmptySlotReason,
    ForbiddenKind,
    ForbiddenScope,
    GapError,
    SlotContext,
    gutter_label,
)
from tests.plan_values import CAREER, a_slot, a_window

STUDY = uuid4()
FITNESS = uuid4()

SCOPED_KINDS = [ForbiddenKind.PREP_UNATTRIBUTED, ForbiddenKind.TRANSIT_UNATTRIBUTED]

# Every word that states a quantity above one. ``one`` is absent deliberately: "one label per
# reason" stays true at any size, and every larger number is a claim about how many members exist.
COUNTING_WORDS = frozenset({"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"})


def counted_in(text: str) -> set[str]:
    """Every word and numeral in this text that states a quantity above one."""
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    return {token for token in tokens if token in COUNTING_WORDS or _is_above_one(token)}


def _is_above_one(token: str) -> bool:
    return token.isdigit() and int(token) > 1


class TestTheVocabularies:
    def test_a_window_forbids_everything_or_named_areas(self) -> None:
        """Two members where the anchor type's own control has three.

        A type that forbids nothing generates no window, so ``none`` has nothing to name here.
        """
        assert [scope.value for scope in ForbiddenScope] == ["all", "areas"]

    def test_there_are_three_kinds_of_forbidden_span(self) -> None:
        assert [kind.value for kind in ForbiddenKind] == [
            "recovery",
            "prep_unattributed",
            "transit_unattributed",
        ]

    def test_every_reason_a_slot_is_empty_is_named_here(self) -> None:
        assert [reason.value for reason in EmptySlotReason] == [
            "no_eligible_content",
            "off_plan",
            "blocked_by_constraint",
            "not_solved",
            "elapsed",
            "dropped_leg",
        ]

    def test_the_reason_vocabulary_counts_its_own_members_nowhere(self) -> None:
        """A docstring stating how many reasons exist goes false when the next one lands.

        Asserted rather than reviewed because the sentence it guards is the one a reader trusts
        to tell them what the members have in common, and a stale count is the part of it they
        cannot check.
        """
        assert counted_in(EmptySlotReason.__doc__ or "") == set()


class TestWhatAWindowForbids:
    def test_a_scoped_window_names_the_areas_it_forbids(self) -> None:
        window = a_window(scope=ForbiddenScope.AREAS, forbidden_area_ids=(CAREER, STUDY))

        assert window.forbids(CAREER)
        assert window.forbids(STUDY)
        assert not window.forbids(FITNESS)

    def test_a_window_that_forbids_everything_forbids_an_area_declared_later(self) -> None:
        """Which is why ``all`` exists: listing every Area stops being correct on the next one."""
        window = a_window(scope=ForbiddenScope.ALL, forbidden_area_ids=())

        assert window.forbids(uuid4())

    def test_a_scoped_window_with_no_areas_forbids_nothing_and_is_refused(self) -> None:
        with pytest.raises(GapError, match="names the Areas it forbids"):
            a_window(scope=ForbiddenScope.AREAS, forbidden_area_ids=())

    def test_a_window_that_forbids_everything_names_no_areas(self) -> None:
        with pytest.raises(GapError, match="names no Areas"):
            a_window(scope=ForbiddenScope.ALL, forbidden_area_ids=(CAREER,))

    @pytest.mark.parametrize("kind", SCOPED_KINDS, ids=[kind.value for kind in SCOPED_KINDS])
    def test_an_unattributed_buffer_cannot_be_scoped_to_areas(self, kind: ForbiddenKind) -> None:
        """It became a window because its buffer had no Area, so there is none to scope it to."""
        with pytest.raises(GapError, match="forbids every Area"):
            a_window(kind=kind, scope=ForbiddenScope.AREAS, forbidden_area_ids=(CAREER,))

    @pytest.mark.parametrize("kind", SCOPED_KINDS, ids=[kind.value for kind in SCOPED_KINDS])
    def test_an_unattributed_buffer_forbids_everything(self, kind: ForbiddenKind) -> None:
        window = a_window(kind=kind, scope=ForbiddenScope.ALL, forbidden_area_ids=())

        assert window.kind is kind

    def test_recovery_is_the_one_kind_a_user_scopes(self) -> None:
        assert a_window(kind=ForbiddenKind.RECOVERY, scope=ForbiddenScope.AREAS).forbids(CAREER)

    def test_a_list_of_forbidden_areas_is_held_as_a_tuple(self) -> None:
        """So a window read back from a stored document cannot change under its holder."""
        areas = [CAREER, STUDY]
        window = a_window(forbidden_area_ids=areas)
        areas.clear()

        assert window.forbidden_area_ids == (CAREER, STUDY)

    def test_a_window_with_no_label_explains_nothing(self) -> None:
        with pytest.raises(GapError, match="explains nothing"):
            a_window(label="")

    def test_a_label_of_whitespace_is_not_judged_here(self) -> None:
        """Characterization, deliberately.

        What counts as whitespace and what counts as unreadable is one class with one
        definition, and it lives at the boundary that fits publisher text to a column. A second
        definition here would diverge from that one the first time either changed.
        """
        assert a_window(label=" ").label == " "


class TestWhatTheDenominatorReadsAWindowAs:
    @pytest.mark.parametrize(
        ("kind", "scope", "expected"),
        [
            (ForbiddenKind.RECOVERY, ForbiddenScope.ALL, OccupancyKind.RECOVERY_ALL),
            (ForbiddenKind.RECOVERY, ForbiddenScope.AREAS, OccupancyKind.RECOVERY_AREAS),
            (
                ForbiddenKind.PREP_UNATTRIBUTED,
                ForbiddenScope.ALL,
                OccupancyKind.UNATTRIBUTED_BUFFER,
            ),
            (
                ForbiddenKind.TRANSIT_UNATTRIBUTED,
                ForbiddenScope.ALL,
                OccupancyKind.UNATTRIBUTED_BUFFER,
            ),
        ],
        ids=["recovery, all", "recovery, areas", "prep", "transit"],
    )
    def test_every_representable_window_maps_to_one_occupancy_kind(
        self, kind: ForbiddenKind, scope: ForbiddenScope, expected: OccupancyKind
    ) -> None:
        areas = (CAREER,) if scope is ForbiddenScope.AREAS else ()
        window = a_window(kind=kind, scope=scope, forbidden_area_ids=areas)

        assert window.occupancy_kind is expected

    @pytest.mark.parametrize(
        ("kind", "scope"),
        [
            (ForbiddenKind.RECOVERY, ForbiddenScope.ALL),
            (ForbiddenKind.RECOVERY, ForbiddenScope.AREAS),
            (ForbiddenKind.PREP_UNATTRIBUTED, ForbiddenScope.ALL),
            (ForbiddenKind.TRANSIT_UNATTRIBUTED, ForbiddenScope.ALL),
        ],
        ids=["recovery, all", "recovery, areas", "prep", "transit"],
    )
    def test_a_window_leaves_the_denominator_exactly_when_no_area_can_claim_it(
        self, kind: ForbiddenKind, scope: ForbiddenScope
    ) -> None:
        """FW2, asserted as agreement with the subtraction table rather than restated.

        The table lives in ``discretionary`` and this mapping is the bridge into it, so what is
        checked here is that the two answer the same question the same way.
        """
        areas = (CAREER,) if scope is ForbiddenScope.AREAS else ()
        window = a_window(kind=kind, scope=scope, forbidden_area_ids=areas)

        assert is_subtracted(window.occupancy_kind) is (window.scope is ForbiddenScope.ALL)


class TestTheGutterLabels:
    @pytest.mark.parametrize(
        ("reason", "expected"),
        [
            (EmptySlotReason.NO_ELIGIBLE_CONTENT, "no eligible Career content"),
            (EmptySlotReason.OFF_PLAN, "off plan"),
            (EmptySlotReason.BLOCKED_BY_CONSTRAINT, "no legal window"),
            (EmptySlotReason.NOT_SOLVED, "content not yet chosen"),
            (EmptySlotReason.ELAPSED, "already begun"),
            (EmptySlotReason.DROPPED_LEG, "journey dropped"),
        ],
        # Enum order, so a case's id names the member it runs. Written in another order the ids,
        # which are generated from the enum, label each case with a different member's name.
        ids=[reason.value for reason in EmptySlotReason],
    )
    def test_each_reason_renders_its_one_label(
        self, reason: EmptySlotReason, expected: str
    ) -> None:
        assert gutter_label(reason, SlotContext("Career")) == expected

    def test_an_off_plan_slot_names_the_period_when_the_user_named_it(self) -> None:
        context = SlotContext("Career", off_plan_label="Italy")

        assert gutter_label(EmptySlotReason.OFF_PLAN, context) == "off plan · Italy"

    def test_an_unnamed_off_plan_period_still_explains_the_gap(self) -> None:
        """A span needs no name to suspend scheduling, so the label cannot require one."""
        assert gutter_label(EmptySlotReason.OFF_PLAN, SlotContext("Career")) == "off plan"

    def test_a_period_label_reaches_no_other_reason(self) -> None:
        """The conditional half lives inside the off-plan renderer, so nothing else reads it."""
        context = SlotContext("Career", off_plan_label="Italy")

        assert gutter_label(EmptySlotReason.NOT_SOLVED, context) == "content not yet chosen"

    def test_every_reason_has_a_label(self) -> None:
        """A reason with no entry would raise where the grid renders rather than be caught."""
        labels = {reason: gutter_label(reason, SlotContext("Career")) for reason in EmptySlotReason}

        assert len(labels) == len(EmptySlotReason)

    def test_no_two_reasons_render_the_same_wording(self) -> None:
        rendered = {gutter_label(reason, SlotContext("Career")) for reason in EmptySlotReason}

        assert len(rendered) == len(EmptySlotReason)

    def test_not_solved_does_not_borrow_the_empty_backlog_wording(self) -> None:
        """Nobody looked at the backlog, so claiming it was empty would assert something
        uncomputed. These two are the wordings a reader is likeliest to conflate."""
        not_solved = gutter_label(EmptySlotReason.NOT_SOLVED, SlotContext("Career"))

        assert "eligible" not in not_solved
        assert not_solved != gutter_label(
            EmptySlotReason.NO_ELIGIBLE_CONTENT, SlotContext("Career")
        )

    def test_an_elapsed_slot_borrows_neither_neighbouring_wording(self) -> None:
        """The clock emptied this slot, so a wording about content states something uncomputed.

        Nobody will look at the backlog for it again, which is what separates it from
        ``not_solved``; and whether the Area had content is a question its span never reached,
        which is what separates it from ``no_eligible_content``.
        """
        context = SlotContext("Career")
        elapsed = gutter_label(EmptySlotReason.ELAPSED, context)

        assert elapsed != gutter_label(EmptySlotReason.NOT_SOLVED, context)
        assert elapsed != gutter_label(EmptySlotReason.NO_ELIGIBLE_CONTENT, context)

    def test_a_dropped_leg_borrows_no_neighbouring_wording(self) -> None:
        """A collision emptied this span, so a wording about content or about the clock would
        state something no phase computed. The cause is the collision rule's, and the one fact
        it adds is that the journey was declared at all.
        """
        context = SlotContext("Career")
        dropped = gutter_label(EmptySlotReason.DROPPED_LEG, context)

        assert dropped != gutter_label(EmptySlotReason.NO_ELIGIBLE_CONTENT, context)
        assert dropped != gutter_label(EmptySlotReason.ELAPSED, context)

    def test_a_slot_renders_its_own_reason(self) -> None:
        slot = a_slot(reason=EmptySlotReason.BLOCKED_BY_CONSTRAINT)

        assert slot.gutter_label(SlotContext("Career")) == "no legal window"

    def test_the_area_named_in_a_label_is_the_slots_own(self) -> None:
        assert a_slot().gutter_label(SlotContext("Study")) == "no eligible Study content"
