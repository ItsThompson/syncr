"""Repeated-pin promotion: what the grouping drops, and why three consecutive weeks is a run.

The two properties that decide whether this function works at all are that grouping drops
``occurrence_key`` and that consecutive means consecutive. Without the first every group is a group
of one, whatever the user did; without the second three unrelated weeks would raise a template
change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from syncr_domain.errors import DomainError
from syncr_domain.identity import BindingKind, BindingRef, index_occurrence_key
from syncr_domain.promotion import (
    CONSECUTIVE_WEEKS_FOR_PROMOTION,
    PinPlacement,
    detect_repeated_pins,
)
from syncr_domain.weeks import IsoWeek

ZONE = "Europe/London"
GYM_ID = UUID(int=1)
OTHER_ID = UUID(int=6)
WEEKS = [IsoWeek(year=2026, week=number) for number in (7, 8, 9, 10)]


def pinned(
    *,
    week: IsoWeek,
    occurrence: int = 0,
    hour: int = 13,
    day: int = 1,
    entity_id: UUID = GYM_ID,
) -> PinPlacement:
    """One pin of one habit, in ``week``, at a local time, under a given occurrence key.

    The instant is built from the week's own Monday in UTC, which is the zone the fixture states, so
    the local weekday and hour the grouping reads are the ones the arguments name.
    """
    monday = datetime(week.monday().year, week.monday().month, week.monday().day, tzinfo=UTC)
    return PinPlacement(
        binding=BindingRef(
            kind=BindingKind.HABIT,
            entity_id=entity_id,
            occurrence_key=index_occurrence_key(occurrence),
            split_index=None,
        ),
        iso_week=week,
        starts_at=monday + timedelta(days=day, hours=hour),
        zone=ZONE,
    )


class TestTheGroupingDropsTheOccurrenceKey:
    def test_three_weeks_of_one_habit_at_one_time_are_one_candidate(self) -> None:
        pins = [pinned(week=week) for week in WEEKS[:3]]

        candidates = detect_repeated_pins(pins)

        assert len(candidates) == 1
        assert candidates[0].consecutive_weeks == 3
        assert candidates[0].local_time == "13:00"

    def test_the_group_survives_the_occurrence_key_differing_per_week(self) -> None:
        # An occurrence key is an index within its own week, so two pins of one habit in two weeks
        # never share one. Grouping on the whole binding would find a group of size one every time.
        pins = [
            pinned(week=WEEKS[0], occurrence=0),
            pinned(week=WEEKS[1], occurrence=3),
            pinned(week=WEEKS[2], occurrence=11),
        ]

        assert len(detect_repeated_pins(pins)) == 1

    def test_two_occurrences_in_one_week_at_the_same_time_are_the_same_claim(self) -> None:
        # The same structural statement made twice in one week, which is one week of evidence.
        pins = [
            pinned(week=WEEKS[0], occurrence=0),
            pinned(week=WEEKS[0], occurrence=1),
            pinned(week=WEEKS[1], occurrence=0),
        ]

        assert detect_repeated_pins(pins) == []

    def test_two_different_habits_do_not_share_a_group(self) -> None:
        gym = [pinned(week=week) for week in WEEKS[:3]]
        other = [pinned(week=week, entity_id=OTHER_ID) for week in WEEKS[:3]]

        assert len(detect_repeated_pins([*gym, *other])) == 2


class TestConsecutiveMeansConsecutive:
    def test_three_weeks_with_a_gap_are_not_a_run(self) -> None:
        # Weeks 7, 9 and 11 are a habit of pinning, not a structural pattern.
        scattered = [pinned(week=IsoWeek(year=2026, week=number)) for number in (7, 9, 11)]

        assert detect_repeated_pins(scattered) == []

    def test_two_consecutive_weeks_are_below_the_threshold(self) -> None:
        assert detect_repeated_pins([pinned(week=week) for week in WEEKS[:2]]) == []

    def test_a_run_of_five_is_one_candidate_of_five_rather_than_three_of_three(self) -> None:
        # Asking the same question three times is the nag the product's severity discipline forbids.
        five = [pinned(week=IsoWeek(year=2026, week=number)) for number in (7, 8, 9, 10, 11)]

        candidates = detect_repeated_pins(five)

        assert len(candidates) == 1
        assert candidates[0].consecutive_weeks == 5

    def test_the_longest_run_is_what_a_group_reports(self) -> None:
        mixed = [pinned(week=IsoWeek(year=2026, week=number)) for number in (2, 7, 8, 9, 10, 20)]

        assert detect_repeated_pins(mixed)[0].consecutive_weeks == 4

    def test_a_run_across_a_year_boundary_is_still_a_run(self) -> None:
        # 2026-W53 precedes 2027-W01, so a week number alone does not decide the answer.
        across = [
            pinned(week=IsoWeek(year=2026, week=52)),
            pinned(week=IsoWeek(year=2026, week=53)),
            pinned(week=IsoWeek(year=2027, week=1)),
        ]

        assert detect_repeated_pins(across)[0].consecutive_weeks == 3

    def test_the_threshold_is_configurable_and_defaults_to_three(self) -> None:
        two_weeks = [pinned(week=week) for week in WEEKS[:2]]

        assert CONSECUTIVE_WEEKS_FOR_PROMOTION == 3
        assert detect_repeated_pins(two_weeks) == []
        assert len(detect_repeated_pins(two_weeks, consecutive_weeks=2)) == 1

    def test_a_run_of_one_is_refused_because_it_is_not_a_repetition(self) -> None:
        with pytest.raises(DomainError, match="not a repetition"):
            detect_repeated_pins([pinned(week=WEEKS[0])], consecutive_weeks=1)


class TestTheLocalTimeIsPartOfTheGroup:
    def test_the_same_habit_at_two_different_hours_is_two_groups(self) -> None:
        early = [pinned(week=week, hour=6) for week in WEEKS[:3]]
        late = [pinned(week=week, hour=19) for week in WEEKS[:3]]

        candidates = detect_repeated_pins([*early, *late])

        assert {one.local_time for one in candidates} == {"06:00", "19:00"}

    def test_the_same_hour_on_two_different_weekdays_is_two_groups(self) -> None:
        # A template entry is declared for a weekday, so Tuesday at 13:00 and Thursday at 13:00 are
        # two different template changes to propose.
        tuesday = [pinned(week=week, day=1) for week in WEEKS[:3]]
        thursday = [pinned(week=week, day=3) for week in WEEKS[:3]]

        candidates = detect_repeated_pins([*tuesday, *thursday])

        assert len(candidates) == 2
        assert {one.weekday for one in candidates} == {2, 4}

    def test_a_local_time_carrying_minutes_renders_them(self) -> None:
        # A pin lands on the fifteen-minute grid, so a group's own time is not always on the hour.
        quarter_past = [
            PinPlacement(
                binding=one.binding,
                iso_week=one.iso_week,
                starts_at=one.starts_at + timedelta(minutes=45),
                zone=ZONE,
            )
            for one in (pinned(week=week) for week in WEEKS[:3])
        ]

        assert detect_repeated_pins(quarter_past)[0].local_time == "13:45"

    def test_an_empty_pin_list_finds_nothing(self) -> None:
        assert detect_repeated_pins([]) == []
