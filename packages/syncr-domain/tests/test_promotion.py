"""Repeated-pin promotion: what the grouping drops, why three consecutive weeks is a run, and the
identity a candidate is addressed by.

The two properties that decide whether this function works at all are that grouping drops
``occurrence_key`` and that consecutive means consecutive. Without the first every group is a group
of one, whatever the user did; without the second three unrelated weeks would raise a template
change.

The third property is newer and is about the answer rather than the finding: a candidate is
addressed by the group it was found by, so an accept names one pattern and a decline silences the
same one, and a run that grows by a week is not a new question.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from urllib.parse import quote
from uuid import UUID

import pytest

from syncr_domain.errors import DomainError
from syncr_domain.identity import BindingKind, BindingRef, index_occurrence_key
from syncr_domain.promotion import (
    CONSECUTIVE_WEEKS_FOR_PROMOTION,
    PinPlacement,
    PromotionRef,
    PromotionRefError,
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
    superseded_hour: int = 7,
) -> PinPlacement:
    """One pin of one habit, in ``week``, at a local time, under a given occurrence key.

    The instant is built from the week's own Monday in UTC, which is the zone the fixture states, so
    the local weekday and hour the grouping reads are the ones the arguments name.

    ``superseded_hour`` is where the plan held the block before the pin, and it defaults to a
    DIFFERENT hour, because a pin that moved nothing is evidence of nothing and the rule drops one.
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
        superseded_at=monday + timedelta(days=day, hours=superseded_hour),
        zone=ZONE,
    )


class TestTheGroupingDropsTheOccurrenceKey:
    def test_three_weeks_of_one_habit_at_one_time_are_one_candidate(self) -> None:
        pins = [pinned(week=week) for week in WEEKS[:3]]

        candidates = detect_repeated_pins(pins)

        assert len(candidates) == 1
        assert candidates[0].consecutive_weeks == 3
        assert candidates[0].ref.local_time == "13:00"

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

        assert {one.ref.local_time for one in candidates} == {"06:00", "19:00"}

    def test_the_same_hour_on_two_different_weekdays_is_two_groups(self) -> None:
        # A template entry is declared for a weekday, so Tuesday at 13:00 and Thursday at 13:00 are
        # two different template changes to propose.
        tuesday = [pinned(week=week, day=1) for week in WEEKS[:3]]
        thursday = [pinned(week=week, day=3) for week in WEEKS[:3]]

        candidates = detect_repeated_pins([*tuesday, *thursday])

        assert len(candidates) == 2
        assert {one.ref.weekday for one in candidates} == {2, 4}

    def test_a_local_time_carrying_minutes_renders_them(self) -> None:
        # A pin lands on the fifteen-minute grid, so a group's own time is not always on the hour.
        quarter_past = [
            PinPlacement(
                binding=one.binding,
                iso_week=one.iso_week,
                starts_at=one.starts_at + timedelta(minutes=45),
                superseded_at=one.superseded_at,
                zone=ZONE,
            )
            for one in (pinned(week=week) for week in WEEKS[:3])
        ]

        assert detect_repeated_pins(quarter_past)[0].ref.local_time == "13:45"

    def test_an_empty_pin_list_finds_nothing(self) -> None:
        assert detect_repeated_pins([]) == []


class TestAPinThatMovedNothingIsEvidenceOfNothing:
    def test_three_weeks_of_pinning_in_place_raise_no_candidate(self) -> None:
        """The reader confirmed where the plan already put it, three weeks running.

        Counting those would ask them to move a template entry to the time it already holds, and the
        accept that followed would be a no-op whose own sentence said so.
        """
        in_place = [pinned(week=week, superseded_hour=13) for week in WEEKS[:3]]

        assert detect_repeated_pins(in_place) == []

    def test_a_week_pinned_in_place_does_not_lengthen_a_run(self) -> None:
        # Weeks 7 and 8 moved it and week 9 confirmed it, which is two weeks of evidence.
        pins = [
            pinned(week=WEEKS[0]),
            pinned(week=WEEKS[1]),
            pinned(week=WEEKS[2], superseded_hour=13),
        ]

        assert detect_repeated_pins(pins) == []

    def test_a_pin_that_moved_is_read_as_moved(self) -> None:
        # The property both readers pass their two instants for, stated on its own.
        assert pinned(week=WEEKS[0]).moved
        assert not pinned(week=WEEKS[0], superseded_hour=13).moved


class TestTheIdentityACandidateIsAddressedBy:
    def test_a_candidate_is_addressed_by_the_group_it_was_found_by(self) -> None:
        # Nothing stores a candidate, so the identifier has to be derivable from the pattern. These
        # are the four values `_group_of` groups on, in the order the reference renders them.
        (candidate,) = detect_repeated_pins([pinned(week=week) for week in WEEKS[:3]])

        assert candidate.ref.id == f"habit.{GYM_ID}.2.780"

    def test_the_identifier_is_unchanged_by_url_encoding(self) -> None:
        """Which is why the separator is a full stop and not a colon.

        The identifier's only job is to travel in a path and come back. A colon is legal there and
        is percent-encoded by the generated client anyway, so one value reached the route under two
        spellings and a router library either side read the tail as a parameter of its own. A value
        ``quote`` leaves alone has one spelling everywhere.
        """
        (candidate,) = detect_repeated_pins([pinned(week=week) for week in WEEKS[:3]])

        assert quote(candidate.ref.id, safe="") == candidate.ref.id

    def test_the_identifier_round_trips_through_parse(self) -> None:
        (candidate,) = detect_repeated_pins([pinned(week=week) for week in WEEKS[:3]])

        assert PromotionRef.parse(candidate.ref.id) == candidate.ref

    def test_a_run_that_grows_keeps_the_identifier_a_decline_silenced(self) -> None:
        # The whole reason the week count is not part of the identity: a fourth week must not ask a
        # question the reader has already answered.
        (three,) = detect_repeated_pins([pinned(week=week) for week in WEEKS[:3]])
        (four,) = detect_repeated_pins([pinned(week=week) for week in WEEKS])

        assert four.consecutive_weeks == 4
        assert four.ref.id == three.ref.id

    @pytest.mark.parametrize(
        "malformed",
        [
            "",
            "habit",
            f"habit.{GYM_ID}.2",
            f"habit.{GYM_ID}.2.780.extra",
            f"pastime.{GYM_ID}.2.780",
            "habit.not-a-uuid.2.780",
            f"habit.{GYM_ID}.x.780",
            f"habit.{GYM_ID}.0.780",
            f"habit.{GYM_ID}.8.780",
            f"habit.{GYM_ID}.2.-1",
            f"habit.{GYM_ID}.2.1440",
            f"habit:{GYM_ID}:2:780",
        ],
    )
    def test_a_value_this_class_did_not_produce_is_refused(self, malformed: str) -> None:
        # An accept edits a template and a decline silences a question, so a reference neither
        # produced nor parseable must reach neither.
        with pytest.raises(PromotionRefError):
            PromotionRef.parse(malformed)

    def test_the_wall_time_and_the_rendered_time_are_one_derivation(self) -> None:
        ref = PromotionRef(kind=BindingKind.HABIT, entity_id=GYM_ID, weekday=2, minute_of_day=825)

        assert ref.wall_time == time(13, 45)
        assert ref.local_time == "13:45"

    def test_midnight_is_a_legal_minute_of_the_day(self) -> None:
        # The lower bound of the range, which a pin on a block starting at 00:00 reaches.
        ref = PromotionRef(kind=BindingKind.ROUTINE, entity_id=GYM_ID, weekday=7, minute_of_day=0)

        assert ref.local_time == "00:00"
        assert PromotionRef.parse(ref.id) == ref
