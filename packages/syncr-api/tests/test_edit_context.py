"""The feature snapshot's own invariants, the round trip, and the deadline match on a split task.

Pure tests, no database. Four groups:

1. The seven-term guard: exactly the objective's terms, no more, no fewer.
2. The bounded-list guard: offset lists and rejected windows stay bounded.
3. The round trip: stored_context → read_context produces an equal value.
4. The deadline match on a split task chunk (M1 fix: matches on entity, not binding).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from syncr_api.plans.edit_context import (
    NEAREST,
    REJECTED_WINDOWS,
    EditContext,
    RejectedWindow,
)
from syncr_api.plans.errors import EditContextRejected
from syncr_api.plans.stored_contexts import read_context, stored_context
from syncr_solver.weights import OBJECTIVE_TERMS

AREA_ID = uuid4()
ZONE = "Europe/London"

A_BREAKDOWN = {term: float(i) for i, term in enumerate(OBJECTIVE_TERMS)}


def a_context(**overrides: object) -> EditContext:
    """A fully populated context, every field set to a non-default value."""
    defaults: dict[str, object] = {
        "weekday": 3,
        "accepted_start_minute_of_day": 840,
        "proposed_start_minute_of_day": 480,
        "duration_minutes": 60,
        "zone": ZONE,
        "objective_breakdown": A_BREAKDOWN,
        "discretionary_minutes": 5880,
        "unallocated_minutes": 2000,
        "blocks_in_day": 4,
        "pinned_blocks_in_week": 2,
        "area_id": AREA_ID,
        "area_floor_minutes": 300,
        "area_placed_minutes": 120,
        "area_target_minutes": 600,
        "gap_before_minutes": 30,
        "gap_after_minutes": 45,
        "adjacent_area_before": uuid4(),
        "adjacent_area_after": None,
        "anchor_offsets_minutes": (-120, 60, 180),
        "forbidden_offsets_minutes": (-60,),
        "rejected_windows": (
            RejectedWindow(offset_minutes=-180, duration_minutes=60, rule="past_block"),
            RejectedWindow(offset_minutes=30, duration_minutes=30, rule="off_plan"),
        ),
        "was_deadline_constrained": True,
        "days_until_deadline": 3,
        "inside_off_plan": True,
    }
    return EditContext(**{**defaults, **overrides})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The seven-term guard
# ---------------------------------------------------------------------------


class TestSevenTermGuard:
    def test_exactly_the_seven_terms_passes(self) -> None:
        ctx = a_context()
        assert set(ctx.objective_breakdown) == set(OBJECTIVE_TERMS)

    def test_a_missing_term_is_refused(self) -> None:
        incomplete = {k: v for k, v in A_BREAKDOWN.items() if k != "churn"}
        with pytest.raises(EditContextRejected, match="seven terms"):
            a_context(objective_breakdown=incomplete)

    def test_an_extra_term_is_refused(self) -> None:
        extra = {**A_BREAKDOWN, "novelty": 1.0}
        with pytest.raises(EditContextRejected, match="seven terms"):
            a_context(objective_breakdown=extra)

    def test_six_terms_names_them(self) -> None:
        wrong = dict(list(A_BREAKDOWN.items())[:6])
        with pytest.raises(EditContextRejected):
            a_context(objective_breakdown=wrong)


# ---------------------------------------------------------------------------
# Bounded lists (E3)
# ---------------------------------------------------------------------------


class TestBoundedLists:
    def test_anchor_offsets_at_the_bound_passes(self) -> None:
        a_context(anchor_offsets_minutes=tuple(range(NEAREST)))

    def test_anchor_offsets_over_the_bound_is_refused(self) -> None:
        with pytest.raises(EditContextRejected, match="bounded"):
            a_context(anchor_offsets_minutes=tuple(range(NEAREST + 1)))

    def test_forbidden_offsets_over_the_bound_is_refused(self) -> None:
        with pytest.raises(EditContextRejected, match="bounded"):
            a_context(forbidden_offsets_minutes=tuple(range(NEAREST + 1)))

    def test_rejected_windows_at_the_bound_passes(self) -> None:
        windows = tuple(
            RejectedWindow(offset_minutes=i * 10, duration_minutes=15, rule="test")
            for i in range(REJECTED_WINDOWS)
        )
        a_context(rejected_windows=windows)

    def test_rejected_windows_over_the_bound_is_refused(self) -> None:
        windows = tuple(
            RejectedWindow(offset_minutes=i * 10, duration_minutes=15, rule="test")
            for i in range(REJECTED_WINDOWS + 1)
        )
        with pytest.raises(EditContextRejected, match="bounded"):
            a_context(rejected_windows=windows)


# ---------------------------------------------------------------------------
# Other guards
# ---------------------------------------------------------------------------


class TestGuards:
    def test_weekday_zero_is_refused(self) -> None:
        with pytest.raises(EditContextRejected, match="weekday"):
            a_context(weekday=0)

    def test_weekday_eight_is_refused(self) -> None:
        with pytest.raises(EditContextRejected, match="weekday"):
            a_context(weekday=8)

    def test_zero_duration_is_refused(self) -> None:
        with pytest.raises(EditContextRejected, match="placement"):
            a_context(duration_minutes=0)

    def test_a_floor_with_no_area_is_refused(self) -> None:
        with pytest.raises(EditContextRejected, match="floor"):
            a_context(area_id=None, area_floor_minutes=300)

    def test_no_area_and_no_floor_passes(self) -> None:
        a_context(area_id=None, area_floor_minutes=None)


# ---------------------------------------------------------------------------
# The round trip (proves the serializer is faithful)
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_a_fully_populated_context_survives_the_round_trip(self) -> None:
        original = a_context()
        rebuilt = read_context(stored_context(original))
        # Compare field by field for a clear diff on failure
        for field in dataclasses.fields(EditContext):
            assert getattr(rebuilt, field.name) == getattr(original, field.name), field.name

    def test_negative_offsets_survive(self) -> None:
        original = a_context(
            anchor_offsets_minutes=(-240, -60, 120),
            days_until_deadline=-2,
        )
        rebuilt = read_context(stored_context(original))
        assert rebuilt.anchor_offsets_minutes == (-240, -60, 120)
        assert rebuilt.days_until_deadline == -2

    def test_inside_off_plan_true_survives(self) -> None:
        original = a_context(inside_off_plan=True)
        rebuilt = read_context(stored_context(original))
        assert rebuilt.inside_off_plan is True

    def test_rejected_windows_survive(self) -> None:
        windows = (
            RejectedWindow(offset_minutes=-180, duration_minutes=60, rule="past_block"),
            RejectedWindow(offset_minutes=30, duration_minutes=30, rule="off_plan"),
        )
        original = a_context(rejected_windows=windows)
        rebuilt = read_context(stored_context(original))
        assert rebuilt.rejected_windows == windows


# ---------------------------------------------------------------------------
# The deadline match on a split task (M1)
# ---------------------------------------------------------------------------


class TestDeadlineMatch:
    def test_a_split_chunk_matches_its_task_by_entity(self) -> None:
        """A split block carries split_index=0 while EligibleTask carries None."""
        from syncr_api.pins.features import _deadline_of
        from syncr_domain.habits import BindingSource
        from syncr_domain.identity import BindingKind, BindingRef
        from syncr_domain.intervals import Interval
        from syncr_domain.plan import Block
        from syncr_domain.reasons import Bound, ReasonRecord
        from syncr_domain.tasks import Priority
        from syncr_domain.weeks import IsoWeek
        from syncr_solver.inputs import EligibleTask, SolveInputs

        task_id = uuid4()
        deadline = datetime(2026, 2, 14, 9, 0, tzinfo=UTC)

        # The eligible task has no split_index
        task_binding = BindingRef(kind=BindingKind.TASK, entity_id=task_id, occurrence_key="00")
        # The block IS a chunk: split_index=1
        chunk_binding = BindingRef(
            kind=BindingKind.TASK, entity_id=task_id, occurrence_key="00", split_index=1
        )
        block = Block(
            iso_week=IsoWeek(2026, 7),
            interval=Interval(
                datetime(2026, 2, 12, 14, 0, tzinfo=UTC),
                datetime(2026, 2, 12, 15, 0, tzinfo=UTC),
            ),
            binding=chunk_binding,
            title="Gym (2/3)",
            reason=ReasonRecord((Bound(source=BindingSource.QUEUE, selected="picked"),)),
            area_id=uuid4(),
            split_count=3,
        )
        eligible = EligibleTask(
            binding=task_binding,
            remaining_minutes=120,
            priority=Priority.NORMAL,
            min_chunk_minutes=30,
            splittable=True,
            area_id=block.area_id,  # type: ignore[arg-type]
            title="Gym",
            deadline=deadline,
        )
        # Minimal SolveInputs with just the eligible task
        from syncr_domain.weeks import IsoWeek

        inputs = SolveInputs(
            iso_week=IsoWeek(2026, 7),
            span=Interval(
                datetime(2026, 2, 9, 0, 0, tzinfo=UTC),
                datetime(2026, 2, 16, 0, 0, tzinfo=UTC),
            ),
            now=datetime(2026, 2, 11, 9, 0, tzinfo=UTC),
            zone_by_date=dict.fromkeys(IsoWeek(2026, 7).dates(), "Europe/London"),
            input_version=1,
            eligible_tasks=(eligible,),
        )

        found = _deadline_of(block, inputs)
        assert found == deadline
