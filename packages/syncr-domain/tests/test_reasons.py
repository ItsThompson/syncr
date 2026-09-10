"""The reason record: the six clause kinds, the widening, and the budget that bounds them.

Three things are asserted here, and the second is the one that keeps the vocabulary at six kinds.

**The record is bounded and never empty.** Every block carries a reason with at least one
clause, and no kind appears more often than the budget allows. A revision document is
appended forever, so an unbounded record grows a store nobody prunes.

**A derived placement satisfies the minimum with one ``bound`` clause.** Five of the six
kinds describe a decision, and materializing a week makes none. Widening ``bound`` to accept
a derivation source is what keeps the vocabulary at six kinds and keeps a block's reason
non-optional, so the four derivation sources are asserted alongside the three habit ones.

**The eight sources are stated once each.** ``BoundSource`` is the union of the habit binding
sources, the derivation sources, and the placed source, so the three are asserted to be disjoint
and to cover the eight the interface renders. A restatement of the three habit sources here would
be a second definition to drift.

**A record has one reading order.** The clauses come out in the budget's own key order
whatever order they went in, so two surfaces rendering one record draw the same rows in the
same sequence, and two clauses of one kind keep the order the caller gave them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, get_args
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from syncr_domain.habits import BindingSource
from syncr_domain.intervals import Interval
from syncr_domain.reasons import (
    CLAUSE_BUDGET,
    MAX_CLAUSES,
    MAX_SHARE,
    Blocked,
    Bound,
    ChurnBaseline,
    Clause,
    DerivationSource,
    Dominant,
    Floor,
    InsteadOf,
    Pinned,
    PlacedSource,
    ReasonError,
    ReasonRecord,
)

if TYPE_CHECKING:
    from syncr_domain.reasons import BoundSource

MONDAY = datetime(2026, 2, 9, tzinfo=UTC)
WINDOW = Interval(MONDAY.replace(hour=6), MONDAY.replace(hour=7))
ELSEWHERE = Interval(MONDAY.replace(hour=13), MONDAY.replace(hour=14))
PINNED_ON = date(2026, 2, 8)

CAREER = uuid4()
APPROVED_REVISION = uuid4()


def a_reason(*clauses: Clause) -> ReasonRecord:
    """One record per test, defaulting to the derivation case a materialized week uses."""
    return ReasonRecord(clauses or (Bound(DerivationSource.ROUTINE, "Sleep · 23:00 + 8h"),))


# One clause of each kind, in the RECORD's reading order, so a generated combination can be
# built by counting rather than by naming the kinds a second time. Written out rather than
# derived from the budget's keys: the order test compares against this literal, and a tuple
# derived from the constant it checks would pass whatever that constant said.
A_CLAUSE_OF_EACH_KIND: tuple[Clause, ...] = (
    Bound(BindingSource.QUEUE, "Tries"),
    Pinned(WINDOW, PINNED_ON),
    InsteadOf(ELSEWHERE, 3.0),
    Blocked(WINDOW, "H2"),
    Dominant("churn", 0.4),
    Floor(
        area_id=CAREER,
        declared_floor_minutes=240,
        floor_minutes=240,
        placed=120,
        of=240,
    ),
)


class TestTheReadingOrder:
    def test_the_clauses_come_out_in_the_budgets_own_order(self) -> None:
        """Whatever order they went in, so one record has one rendering on every surface."""
        scrambled = tuple(reversed(A_CLAUSE_OF_EACH_KIND))

        assert ReasonRecord(scrambled).clauses == A_CLAUSE_OF_EACH_KIND

    def test_what_determined_the_block_reads_first_and_the_area_floor_last(self) -> None:
        """The order runs from what is specific to this block to what is general to the week."""
        kinds = [kind.__name__ for kind in CLAUSE_BUDGET]

        assert kinds == ["Bound", "Pinned", "InsteadOf", "Blocked", "Dominant", "Floor"]

    def test_the_two_rejected_windows_keep_the_order_they_arrived_in(self) -> None:
        """The top two, in that order: a stable sort by kind cannot reorder one kind."""
        first = Blocked(WINDOW, "anchor_overlap")
        second = Blocked(ELSEWHERE, "area_daily_cap")

        assert ReasonRecord((second, first)).clauses == (second, first)

    @given(order=st.permutations(A_CLAUSE_OF_EACH_KIND))
    def test_every_permutation_of_the_six_reads_the_same_way(self, order: list[Clause]) -> None:
        assert ReasonRecord(tuple(order)).clauses == A_CLAUSE_OF_EACH_KIND


class TestTheClauseVocabulary:
    def test_there_are_six_kinds_and_the_union_states_them(self) -> None:
        """Asserted against the union itself, so a seventh kind fails a test not a review."""
        assert set(get_args(Clause.__value__)) == {
            Blocked,
            Dominant,
            Bound,
            Floor,
            Pinned,
            InsteadOf,
        }

    def test_every_kind_carries_a_budget(self) -> None:
        """A kind with no budget would be unrepresentable, so the two lists are one set."""
        assert set(CLAUSE_BUDGET) == set(get_args(Clause.__value__))

    def test_every_kind_has_a_place_in_the_reading_order(self) -> None:
        """A kind with no rank would raise on construction rather than render last."""
        record = ReasonRecord(A_CLAUSE_OF_EACH_KIND)

        assert {type(clause) for clause in record.clauses} == set(get_args(Clause.__value__))

    def test_only_the_rejected_windows_are_allowed_twice(self) -> None:
        assert CLAUSE_BUDGET[Blocked] == 2
        assert {kind for kind, allowed in CLAUSE_BUDGET.items() if allowed == 1} == {
            Dominant,
            Bound,
            Floor,
            Pinned,
            InsteadOf,
        }

    def test_the_whole_record_is_bounded_at_seven_clauses(self) -> None:
        assert MAX_CLAUSES == 7


class TestTheEightBoundSources:
    def test_the_union_covers_the_eight_the_interface_renders(self) -> None:
        sources = (
            {source.value for source in BindingSource}
            | {source.value for source in DerivationSource}
            | {source.value for source in PlacedSource}
        )

        assert sources == {
            "fixed",
            "rotation",
            "queue",
            "routine",
            "template_entry",
            "anchor",
            "anchor_type",
            "solver",
        }

    def test_the_three_vocabularies_are_disjoint(self) -> None:
        """A value in two vocabularies would make the source of a stored clause ambiguous."""
        spelled = [
            {source.value for source in vocabulary}
            for vocabulary in (BindingSource, DerivationSource, PlacedSource)
        ]

        assert sum(len(words) for words in spelled) == len(set().union(*spelled))

    def test_the_habit_sources_are_not_restated_here(self) -> None:
        """The three live on the habit, which is what resolves them. One statement, two readers."""
        assert [source.value for source in DerivationSource] == [
            "routine",
            "template_entry",
            "anchor",
            "anchor_type",
        ]

    @pytest.mark.parametrize(
        "source",
        [*BindingSource, *DerivationSource, *PlacedSource],
        ids=[source.value for source in (*BindingSource, *DerivationSource, *PlacedSource)],
    )
    def test_a_bound_clause_accepts_every_one_of_them(self, source: BoundSource) -> None:
        assert Bound(source, "Legs").source is source


class TestADerivedBlockSatisfiesTheMinimum:
    @pytest.mark.parametrize(
        ("source", "selected"),
        [
            (DerivationSource.ROUTINE, "Sleep · 23:00 + 8h"),
            (DerivationSource.TEMPLATE_ENTRY, "Weekday · 06:45"),
            (DerivationSource.ANCHOR, "Google · Personal, read only"),
            (DerivationSource.ANCHOR_TYPE, "Interview · transit out, 30m before"),
        ],
        ids=[source.value for source in DerivationSource],
    )
    def test_one_bound_clause_is_a_whole_reason(
        self, source: DerivationSource, selected: str
    ) -> None:
        """Materializing runs no search and evaluates no objective, so this is all there is.

        Without the widening, a materialized revision would be an exception to the rule that
        every block carries a reason, or it would need a seventh clause kind.
        """
        record = ReasonRecord((Bound(source, selected),))

        assert record.clauses == (Bound(source, selected),)

    def test_a_derived_block_may_also_carry_the_users_own_edit(self) -> None:
        """Fixed by derivation and pinned elsewhere by the user are compatible states."""
        record = a_reason(
            Bound(DerivationSource.TEMPLATE_ENTRY, "Weekday · 06:45"),
            Pinned(WINDOW, PINNED_ON),
            InsteadOf(ELSEWHERE, 12.5),
        )

        assert len(record.clauses) == 3

    def test_a_habit_names_its_binding_source_and_its_cursor(self) -> None:
        clause = Bound(BindingSource.ROTATION, "Legs", cursor="1 of 4")

        assert (clause.source, clause.selected, clause.cursor) == (
            BindingSource.ROTATION,
            "Legs",
            "1 of 4",
        )


class TestTheRecordIsNeverEmptyAndNeverUnbounded:
    def test_a_record_with_no_clauses_is_not_a_reason(self) -> None:
        with pytest.raises(ReasonError, match="at least one clause"):
            ReasonRecord(())

    @given(
        counts=st.lists(st.integers(min_value=0, max_value=2), min_size=6, max_size=6).filter(any)
    )
    def test_any_record_inside_the_budget_is_a_reason(self, counts: list[int]) -> None:
        """Over generated combinations, so the budget is a bound rather than one accepted shape."""
        clauses = [
            clause
            for clause, count in zip(A_CLAUSE_OF_EACH_KIND, counts, strict=True)
            for _ in range(min(count, CLAUSE_BUDGET[type(clause)]))
        ]

        assert len(ReasonRecord(tuple(clauses)).clauses) == len(clauses)

    @given(kind=st.sampled_from(A_CLAUSE_OF_EACH_KIND))
    def test_one_clause_past_the_budget_is_refused_whatever_the_kind(self, kind: Clause) -> None:
        over = (kind,) * (CLAUSE_BUDGET[type(kind)] + 1)

        with pytest.raises(ReasonError, match="bounded per clause kind"):
            ReasonRecord(over)

    def test_two_rejected_windows_are_the_most_a_block_reports(self) -> None:
        two = (Blocked(WINDOW, "H2"), Blocked(ELSEWHERE, "H8"))

        assert ReasonRecord(two).clauses == two

    def test_a_third_rejected_window_exceeds_the_budget(self) -> None:
        with pytest.raises(ReasonError, match="Blocked 3 of 2"):
            ReasonRecord(
                (
                    Blocked(WINDOW, "H2"),
                    Blocked(ELSEWHERE, "H8"),
                    Blocked(WINDOW, "H13"),
                )
            )

    @pytest.mark.parametrize(
        "clause",
        [
            Dominant("churn", 0.4),
            Bound(BindingSource.FIXED, "Anki - F&F"),
            Floor(
                area_id=CAREER,
                declared_floor_minutes=240,
                floor_minutes=240,
                placed=120,
                of=240,
            ),
            Pinned(WINDOW, PINNED_ON),
            InsteadOf(ELSEWHERE, 3.0),
        ],
        ids=["dominant", "bound", "floor", "pinned", "instead of"],
    )
    def test_every_other_kind_appears_at_most_once(self, clause: Clause) -> None:
        with pytest.raises(ReasonError, match="2 of 1"):
            ReasonRecord((clause, clause))

    def test_the_full_budget_is_representable(self) -> None:
        """The bound is a ceiling on a real record rather than a number nothing reaches."""
        record = ReasonRecord(
            (
                Blocked(WINDOW, "H2"),
                Blocked(ELSEWHERE, "H8"),
                Dominant("churn", 0.4),
                Bound(BindingSource.QUEUE, "Tries"),
                Floor(
                    area_id=CAREER,
                    declared_floor_minutes=240,
                    floor_minutes=240,
                    placed=120,
                    of=240,
                ),
                Pinned(WINDOW, PINNED_ON),
                InsteadOf(ELSEWHERE, 3.0),
            )
        )

        assert len(record.clauses) == MAX_CLAUSES

    def test_a_kind_the_interface_has_no_template_for_is_refused(self) -> None:
        """A record read back from a stored document is where an unknown kind arrives."""
        with pytest.raises(ReasonError, match="six clause kinds"):
            ReasonRecord(("blocked because I said so",))  # type: ignore[arg-type]

    def test_a_list_of_clauses_is_held_as_a_tuple(self) -> None:
        """So the record cannot be changed through the list it was built from."""
        clauses = [Bound(DerivationSource.ANCHOR, "Google · Personal")]
        record = ReasonRecord(clauses)  # type: ignore[arg-type]
        clauses.clear()

        assert len(record.clauses) == 1
        assert isinstance(record.clauses, tuple)


class TestWhatAClauseRefuses:
    @pytest.mark.parametrize("share", [-0.1, 1.01, float("nan"), float("inf")])
    def test_a_share_of_total_cost_is_a_fraction_of_the_whole(self, share: float) -> None:
        """NaN fails the comparison rather than needing a check of its own."""
        with pytest.raises(ReasonError, match="share of total cost"):
            Dominant("churn", share)

    @pytest.mark.parametrize("share", [0.0, 0.5, MAX_SHARE])
    def test_the_whole_range_is_a_share(self, share: float) -> None:
        assert Dominant("churn", share).share == share

    @pytest.mark.parametrize(
        ("declared_floor_minutes", "floor_minutes", "placed", "of"),
        [(-1, 0, 0, 0), (0, -1, 0, 0), (0, 0, -1, 0), (0, 0, 0, -1)],
        ids=[
            "a negative declared floor",
            "a negative rule floor",
            "negative minutes placed",
            "a negative requirement",
        ],
    )
    def test_a_floor_clause_counts_minutes(
        self, declared_floor_minutes: int, floor_minutes: int, placed: int, of: int
    ) -> None:
        with pytest.raises(ReasonError, match="none of these is negative"):
            Floor(
                area_id=CAREER,
                declared_floor_minutes=declared_floor_minutes,
                floor_minutes=floor_minutes,
                placed=placed,
                of=of,
            )

    def test_a_floor_may_be_over_placed(self) -> None:
        """A week that beats a floor is ordinary, so `placed` above `of` is not an error."""
        assert (
            Floor(
                area_id=CAREER,
                declared_floor_minutes=240,
                floor_minutes=240,
                placed=300,
                of=240,
            ).placed
            == 300
        )

    @pytest.mark.parametrize("delta", [float("nan"), float("inf"), float("-inf")])
    def test_a_pin_cost_a_finite_number_of_objective_units(self, delta: float) -> None:
        """A NaN compares false against every threshold and renders as itself."""
        with pytest.raises(ReasonError, match="finite number of objective units"):
            InsteadOf(ELSEWHERE, delta)

    def test_a_pin_that_cost_nothing_is_representable(self) -> None:
        """Rejecting a proposed move pins a block where it already was, which costs nothing."""
        assert InsteadOf(ELSEWHERE, 0.0).objective_delta == 0.0


class TestTheChurnBaseline:
    def test_an_approved_revision_and_its_instant_travel_together(self) -> None:
        baseline = ChurnBaseline(APPROVED_REVISION, MONDAY)

        assert baseline.is_measured

    def test_a_week_nobody_approved_names_neither(self) -> None:
        """Churn is zero and the clause states that rather than comparing against a proposal."""
        assert not ChurnBaseline().is_measured

    @pytest.mark.parametrize(
        ("revision_id", "approved_at"),
        [(APPROVED_REVISION, None), (None, MONDAY)],
        ids=["a revision with no instant", "an instant with no revision"],
    )
    def test_half_a_baseline_renders_half_a_sentence(
        self, revision_id: object, approved_at: object
    ) -> None:
        with pytest.raises(ReasonError, match="or neither"):
            ChurnBaseline(revision_id, approved_at)  # type: ignore[arg-type]

    def test_a_dominant_churn_clause_carries_the_baseline_it_measured(self) -> None:
        clause = Dominant("churn", 0.6, ChurnBaseline(APPROVED_REVISION, MONDAY))

        assert clause.baseline is not None
        assert clause.baseline.revision_id == APPROVED_REVISION

    def test_another_term_carries_no_baseline(self) -> None:
        assert Dominant("deadline_risk", 0.9).baseline is None
