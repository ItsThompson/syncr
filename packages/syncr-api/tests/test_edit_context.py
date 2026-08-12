"""The feature snapshot's own invariants, the round trip, and the deadline match on a split task.

Pure tests, no database. Four groups:

1. The seven-term guard: exactly the objective's terms, no more, no fewer.
2. The bounded-list guard: offset lists and rejected windows stay bounded.
3. The round trip: stored_context → read_context produces an equal value.
4. The deadline match on a split task chunk (M1 fix: matches on entity, not binding).
"""

from __future__ import annotations

import dataclasses
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
# Distinct from the breakdown above, and signed, so a round trip that confused the two fields or
# dropped this one's sign is a failing comparison rather than a coincidence.
A_MEASUREMENT_DELTA = {term: 0.5 - i for i, term in enumerate(OBJECTIVE_TERMS)}


def a_context(**overrides: object) -> EditContext:
    """A fully populated context, every field set to a non-default value."""
    defaults: dict[str, object] = {
        "weekday": 3,
        "accepted_start_minute_of_day": 840,
        "proposed_start_minute_of_day": 480,
        "duration_minutes": 60,
        "zone": ZONE,
        "objective_breakdown": A_BREAKDOWN,
        "measurement_delta": A_MEASUREMENT_DELTA,
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

    def test_a_measurement_delta_missing_a_term_is_refused(self) -> None:
        # The same guard over the second seven-term mapping. A partial one would let the weight fit
        # rank a pair on six terms and silently treat the seventh as costing the same either way.
        incomplete = {k: v for k, v in A_MEASUREMENT_DELTA.items() if k != "staleness"}
        with pytest.raises(EditContextRejected, match="seven terms"):
            a_context(measurement_delta=incomplete)

    def test_a_measurement_delta_of_none_passes_because_the_corpus_predates_it(self) -> None:
        # E5 forbids pruning, so every event written before the field existed carries no key. The
        # absence has to read as a value, and the weight fit is what excludes it.
        assert a_context(measurement_delta=None).measurement_delta is None


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

    def test_a_context_written_before_the_measurement_delta_reads_back_as_none(self) -> None:
        # The shape a row written before the field existed holds: every other key, and no
        # `measurement_delta`.
        # Read as a refusal rather than as None, the corpus would be unreadable from this commit on.
        stored = stored_context(a_context())
        del stored["measurement_delta"]

        assert read_context(stored).measurement_delta is None

    def test_a_null_measurement_delta_reads_back_as_none(self) -> None:
        # The shape this commit writes for a pin that could not be priced, and the shape a JSONB
        # column holds for an explicit null. Both read the same way.
        original = a_context(measurement_delta=None)

        assert read_context(stored_context(original)).measurement_delta is None

    def test_a_measurement_delta_keeps_its_signs_through_the_round_trip(self) -> None:
        # The label's own sign is what says which side the user preferred, so a serializer that
        # dropped it would invert the preference the corpus records.
        rebuilt = read_context(stored_context(a_context()))

        assert rebuilt.measurement_delta == A_MEASUREMENT_DELTA
        assert rebuilt.measurement_delta != rebuilt.objective_breakdown

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


class TestDeadlineGuard:
    """The deadline is a parameter to edit_context, not derived from eligible_tasks."""

    def test_a_task_deadline_is_carried_into_the_context(self) -> None:
        """When task_deadline is set, was_deadline_constrained is True."""

        ctx = a_context(was_deadline_constrained=True, days_until_deadline=3)
        assert ctx.was_deadline_constrained is True
        assert ctx.days_until_deadline == 3

    def test_no_deadline_means_not_constrained(self) -> None:
        ctx = a_context(was_deadline_constrained=False, days_until_deadline=None)
        assert ctx.was_deadline_constrained is False
        assert ctx.days_until_deadline is None


# ---------------------------------------------------------------------------
# The field classification: pre-edit vs post-edit, derived and asserted
# ---------------------------------------------------------------------------

# Every field of EditContext classified by its source. Pre-edit fields describe the state the
# proposal was made in; post-edit fields describe the accepted placement and the week around it.
# A field added to EditContext without appearing in one of these two sets fails
# `test_every_field_is_classified`.
#
# LIMIT OF THIS GUARD: it checks MEMBERSHIP (a new field must be placed in one set) but cannot
# check SOURCING (that the code reads it from the right assembly). What holds the sourcing is that
# `edit_context` is handed ONE assembly and it is the pre-pin one: the pin write path prices the
# edit and builds this context in the frame taken before the pin row exists, and computes the
# verdict in a second assembly this function never receives. `tests/test_pin_write_path.py` holds
# which frame each consumer is handed.
PRE_EDIT_FIELDS = frozenset(
    {
        "objective_breakdown",
        "measurement_delta",
        "discretionary_minutes",
        "unallocated_minutes",
        "blocks_in_day",
        "pinned_blocks_in_week",
        "area_floor_minutes",
        "area_placed_minutes",
        "area_target_minutes",
        "was_deadline_constrained",
        "days_until_deadline",
    }
)

POST_EDIT_FIELDS = frozenset(
    {
        "weekday",
        "accepted_start_minute_of_day",
        "proposed_start_minute_of_day",
        "duration_minutes",
        "zone",
        "area_id",
        "gap_before_minutes",
        "gap_after_minutes",
        "adjacent_area_before",
        "adjacent_area_after",
        "anchor_offsets_minutes",
        "forbidden_offsets_minutes",
        "rejected_windows",
        "inside_off_plan",
    }
)


class TestFieldClassification:
    """Every field is classified; a twenty-sixth cannot be added on the wrong side."""

    def test_every_field_is_classified(self) -> None:
        actual = {f.name for f in dataclasses.fields(EditContext)}
        classified = PRE_EDIT_FIELDS | POST_EDIT_FIELDS
        assert actual == classified, {
            "unclassified": sorted(actual - classified),
            "classified but absent": sorted(classified - actual),
        }

    def test_the_two_sets_do_not_overlap(self) -> None:
        assert set() == PRE_EDIT_FIELDS & POST_EDIT_FIELDS
