"""The Habit entity: the three cadences, the two duration shapes, X3, X4, and every bound.

X3 and X4 are asserted in both directions, which is the point of them being one rule stated
twice: a rotation without variants and a non-rotation with them are the two ways a binding
source and its content can disagree, and neither is representable.

The bounds are asserted at the value that passes and the value that does not, because a bound
whose edge is untested is a bound nobody knows the position of.
"""

from __future__ import annotations

from typing import get_args
from uuid import uuid4

import pytest

from syncr_domain.habits import (
    DEFAULT_DEBT_CAP_PERIODS,
    MAX_APPROX_DAYS,
    MAX_DEBT_CAP_PERIODS,
    MAX_DURATION_MINUTES,
    MAX_TIMES_PER_WEEK,
    MAX_VARIANTS,
    MIN_APPROX_DAYS,
    MIN_DEBT_CAP_PERIODS,
    MIN_DURATION_MINUTES,
    VARIANT_MAX_LENGTH,
    BindingSource,
    Cadence,
    CadenceKind,
    Daily,
    Duration,
    EveryApproxDays,
    Habit,
    HabitError,
    MissPolicy,
    TimesPerWeek,
    build_cadence,
    cadence_kind,
    occurrences_per_period,
)
from syncr_domain.snap import SNAP_MINUTES

GYM_SPLIT = ("Shoulder & Arms", "Legs", "Chest & Back", "Cardio")


def habit(**overrides: object) -> Habit:
    """A fixed, forgiving, four-times-a-week habit, with the field under test replaced."""
    fields: dict[str, object] = {
        "id": uuid4(),
        "cadence": TimesPerWeek(4),
        "duration": Duration.fixed(90),
        "miss_policy": MissPolicy.FORGIVE,
        "binding_source": BindingSource.FIXED,
    }
    fields.update(overrides)
    return Habit(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------
# Cadence: three kinds, and nothing else
# --------------------------------------------------------------------------------


def test_the_cadence_union_holds_exactly_the_three_kinds() -> None:
    """`Nothing else` is a property of the type, so it is asserted against the type.

    A fourth cadence added to the union fails here, which is the review this rule needs: a
    template expressing recurrence, or a monthly period, would arrive as exactly that.
    """
    assert set(get_args(Cadence.__value__)) == {TimesPerWeek, Daily, EveryApproxDays}
    assert set(CadenceKind) == {
        CadenceKind.TIMES_PER_WEEK,
        CadenceKind.DAILY,
        CadenceKind.EVERY_APPROX_DAYS,
    }


@pytest.mark.parametrize(
    ("cadence", "kind"),
    [
        (TimesPerWeek(4), CadenceKind.TIMES_PER_WEEK),
        (Daily(), CadenceKind.DAILY),
        (EveryApproxDays(7), CadenceKind.EVERY_APPROX_DAYS),
    ],
)
def test_every_cadence_names_its_stored_kind(cadence: Cadence, kind: CadenceKind) -> None:
    assert cadence_kind(cadence) is kind


@pytest.mark.parametrize(
    "cadence", [TimesPerWeek(1), TimesPerWeek(4), Daily(), EveryApproxDays(2), EveryApproxDays(30)]
)
def test_a_cadence_round_trips_through_the_columns_that_store_it(cadence: Cadence) -> None:
    """The persistence seam, both ways. A row is two numbers and a discriminator."""
    kind = cadence_kind(cadence)
    rebuilt = build_cadence(
        kind,
        times_per_week=cadence.count if isinstance(cadence, TimesPerWeek) else None,
        approx_days=cadence.days if isinstance(cadence, EveryApproxDays) else None,
    )

    assert rebuilt == cadence


@pytest.mark.parametrize(
    ("kind", "times_per_week", "approx_days"),
    [
        (CadenceKind.TIMES_PER_WEEK, None, None),
        (CadenceKind.TIMES_PER_WEEK, 4, 7),
        (CadenceKind.DAILY, 4, None),
        (CadenceKind.DAILY, None, 7),
        (CadenceKind.EVERY_APPROX_DAYS, None, None),
        (CadenceKind.EVERY_APPROX_DAYS, 4, 7),
    ],
)
def test_a_stored_row_whose_numbers_do_not_match_its_kind_is_refused(
    kind: CadenceKind, times_per_week: int | None, approx_days: int | None
) -> None:
    """A row two kinds could be read out of resolves to neither.

    Silently preferring the discriminator would make a row carrying both numbers legal, and a
    later migration reading the other one would disagree with this one about the same row.
    """
    with pytest.raises(HabitError):
        build_cadence(kind, times_per_week=times_per_week, approx_days=approx_days)


@pytest.mark.parametrize("count", [1, MAX_TIMES_PER_WEEK])
def test_a_count_per_week_on_the_bound_is_a_cadence(count: int) -> None:
    assert TimesPerWeek(count).count == count


@pytest.mark.parametrize("count", [0, -1, MAX_TIMES_PER_WEEK + 1])
def test_a_count_per_week_off_the_bound_is_not_a_cadence(count: int) -> None:
    with pytest.raises(HabitError, match="times a week is not a cadence"):
        TimesPerWeek(count)


@pytest.mark.parametrize("days", [MIN_APPROX_DAYS, MAX_APPROX_DAYS])
def test_an_interval_on_the_bound_is_a_cadence(days: int) -> None:
    assert EveryApproxDays(days).days == days


@pytest.mark.parametrize("days", [0, -1, MAX_APPROX_DAYS + 1])
def test_an_interval_off_the_bound_is_not_a_cadence(days: int) -> None:
    with pytest.raises(HabitError, match="is not a cadence"):
        EveryApproxDays(days)


def test_an_interval_of_one_day_names_daily_rather_than_becoming_a_second_spelling_of_it() -> None:
    """Two spellings of one cadence would expand identically and be indistinguishable after."""
    with pytest.raises(HabitError, match="Daily"):
        EveryApproxDays(1)


@pytest.mark.parametrize(
    ("cadence", "expected"),
    [(TimesPerWeek(4), 4), (TimesPerWeek(1), 1), (Daily(), 1), (EveryApproxDays(7), 1)],
)
def test_occurrences_per_period_counts_the_cadence_rather_than_measuring_a_span(
    cadence: Cadence, expected: int
) -> None:
    """A period is the span the cadence repeats over, so an interval cadence holds one."""
    assert occurrences_per_period(cadence) == expected


# --------------------------------------------------------------------------------
# Duration: fixed is min == max
# --------------------------------------------------------------------------------


def test_a_fixed_duration_is_a_range_of_one_value() -> None:
    fixed = Duration.fixed(90)

    assert (fixed.min_minutes, fixed.max_minutes) == (90, 90)
    assert fixed.is_fixed


def test_an_elastic_duration_offers_the_solver_room() -> None:
    elastic = Duration.elastic(min_minutes=30, max_minutes=90)

    assert (elastic.min_minutes, elastic.max_minutes) == (30, 90)
    assert not elastic.is_fixed


@pytest.mark.parametrize("minutes", [MIN_DURATION_MINUTES, MAX_DURATION_MINUTES])
def test_a_duration_on_the_bound_is_a_duration(minutes: int) -> None:
    assert Duration.fixed(minutes).min_minutes == minutes


@pytest.mark.parametrize("minutes", [0, -SNAP_MINUTES, MAX_DURATION_MINUTES + SNAP_MINUTES])
def test_a_duration_off_the_bound_is_not_a_duration(minutes: int) -> None:
    with pytest.raises(HabitError, match="is not a duration"):
        Duration.fixed(minutes)


@pytest.mark.parametrize("minutes", [20, 25, 91])
def test_a_duration_that_misses_the_grid_is_refused_at_the_declaration(minutes: int) -> None:
    """A block's start and end both land on the quarter hour, so its duration has to.

    25 is in this list deliberately, because `docs/prd.md` illustrates elasticity with
    `Leetcode` at 25, 45, and 90 minutes. That figure attaches to a splittable task's chunks,
    which is a different field: `syncr_domain.snap.is_a_snap_multiple` states that a DECLARED
    duration owes the grid the block it materializes into, and a habit occurrence is solver
    output. The nearest expressible habit range is 30 to 90.
    """
    with pytest.raises(HabitError, match="grid"):
        Duration.fixed(minutes)


def test_an_elastic_maximum_below_its_minimum_is_refused() -> None:
    with pytest.raises(HabitError, match="runs backwards"):
        Duration.elastic(min_minutes=90, max_minutes=45)


def test_an_elastic_range_of_one_step_is_the_narrowest_one_that_is_not_fixed() -> None:
    """The boundary between the two shapes: one grid step apart, and `is_fixed` is False."""
    narrow = Duration.elastic(
        min_minutes=MIN_DURATION_MINUTES, max_minutes=MIN_DURATION_MINUTES + SNAP_MINUTES
    )

    assert not narrow.is_fixed
    assert Duration.elastic(
        min_minutes=MIN_DURATION_MINUTES, max_minutes=MIN_DURATION_MINUTES
    ).is_fixed


# --------------------------------------------------------------------------------
# X3 and X4: a binding source and its variants agree, in both directions
# --------------------------------------------------------------------------------


def test_x3_a_rotation_habit_holds_a_non_empty_variant_list() -> None:
    rotating = habit(binding_source=BindingSource.ROTATION, variants=GYM_SPLIT)

    assert rotating.variants == GYM_SPLIT
    assert rotating.rotates


def test_x3_a_rotation_habit_without_variants_is_refused() -> None:
    with pytest.raises(HabitError, match="needs an ordered variant list"):
        habit(binding_source=BindingSource.ROTATION, variants=())


@pytest.mark.parametrize("source", [BindingSource.FIXED, BindingSource.QUEUE])
def test_x4_a_habit_that_does_not_rotate_holds_an_empty_variant_list(
    source: BindingSource,
) -> None:
    assert habit(binding_source=source).variants == ()
    assert not habit(binding_source=source).rotates


@pytest.mark.parametrize("source", [BindingSource.FIXED, BindingSource.QUEUE])
def test_x4_a_habit_that_does_not_rotate_carrying_variants_is_refused(
    source: BindingSource,
) -> None:
    with pytest.raises(HabitError, match="carries no variants"):
        habit(binding_source=source, variants=GYM_SPLIT)


def test_a_queue_habit_records_its_source_and_waits_for_the_solver_to_choose_content() -> None:
    """Queue selection happens at solve time. What a Habit records is that it draws from one."""
    queued = habit(binding_source=BindingSource.QUEUE)

    assert queued.binding_source is BindingSource.QUEUE
    assert queued.variants == ()


def test_a_rotation_of_one_variant_is_a_rotation_that_never_moves() -> None:
    """Legal, and worth pinning: it is the shape a user reaches for while building a split."""
    assert habit(binding_source=BindingSource.ROTATION, variants=("Full body",)).rotates


def test_a_rotation_at_the_variant_bound_is_accepted_and_one_past_it_is_not() -> None:
    at_bound = tuple(f"Day {index}" for index in range(MAX_VARIANTS))
    habit(binding_source=BindingSource.ROTATION, variants=at_bound)

    with pytest.raises(HabitError, match="more than a rotation holds"):
        habit(binding_source=BindingSource.ROTATION, variants=(*at_bound, "one more"))


@pytest.mark.parametrize("variant", ["", "   ", "\t"])
def test_a_variant_with_no_name_names_no_content(variant: str) -> None:
    with pytest.raises(HabitError, match="carries no name"):
        habit(binding_source=BindingSource.ROTATION, variants=("Legs", variant))


def test_a_variant_at_the_length_bound_is_accepted_and_one_past_it_is_not() -> None:
    habit(binding_source=BindingSource.ROTATION, variants=("v" * VARIANT_MAX_LENGTH,))

    with pytest.raises(HabitError, match="characters"):
        habit(binding_source=BindingSource.ROTATION, variants=("v" * (VARIANT_MAX_LENGTH + 1),))


# --------------------------------------------------------------------------------
# The debt cap in periods
# --------------------------------------------------------------------------------


def test_the_debt_cap_defaults_to_two_cadence_periods() -> None:
    assert habit().debt_cap_periods == DEFAULT_DEBT_CAP_PERIODS
    assert DEFAULT_DEBT_CAP_PERIODS == 2


@pytest.mark.parametrize("periods", [MIN_DEBT_CAP_PERIODS, MAX_DEBT_CAP_PERIODS])
def test_a_debt_cap_on_the_bound_is_a_cap(periods: int) -> None:
    assert habit(debt_cap_periods=periods).debt_cap_periods == periods


@pytest.mark.parametrize("periods", [-1, MAX_DEBT_CAP_PERIODS + 1])
def test_a_debt_cap_off_the_bound_is_not_a_cap(periods: int) -> None:
    with pytest.raises(HabitError, match="is not a cap"):
        habit(debt_cap_periods=periods)


def test_a_debt_cap_of_zero_is_refused_because_escalate_already_says_it() -> None:
    """Cap zero forgives every miss and raises the habit on the first, which is `escalate`."""
    with pytest.raises(HabitError, match=MissPolicy.ESCALATE.value):
        habit(miss_policy=MissPolicy.DEBT, debt_cap_periods=0)


def test_the_three_miss_policies_are_the_whole_vocabulary() -> None:
    assert set(MissPolicy) == {MissPolicy.FORGIVE, MissPolicy.DEBT, MissPolicy.ESCALATE}


def test_the_three_binding_sources_are_the_whole_vocabulary() -> None:
    assert set(BindingSource) == {
        BindingSource.FIXED,
        BindingSource.ROTATION,
        BindingSource.QUEUE,
    }


def test_a_habit_carries_no_preferred_time_and_no_cursor() -> None:
    """Two absences that are the design. A preferred time is a Preference; a cursor is derived.

    Asserted against the field set rather than by reading the source, so a field added under
    any name that means either fails here.
    """
    fields = set(Habit.__dataclass_fields__)

    assert fields == {
        "id",
        "cadence",
        "duration",
        "miss_policy",
        "binding_source",
        "variants",
        "debt_cap_periods",
    }
