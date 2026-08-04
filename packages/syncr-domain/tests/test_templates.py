"""The day-shape vocabulary and the one rule a week pattern has: all seven weekdays.

The pattern's rule is asserted from both ends. A complete mapping is a pattern, an incomplete
one is not constructible at all, and the rejection names the weekdays that were left out,
because "invalid pattern" tells the user nothing about which row of the editor to fill in.

``covers`` is what decides how far a template edit reaches, so it is asserted on a day type
that is mapped and on one that is not. Without the second half, a rule stated as "bump when
the pattern covers this day type" would be indistinguishable from "bump always".
"""

from __future__ import annotations

from datetime import UTC, time
from uuid import UUID, uuid4

import pytest

from syncr_domain.snap import SNAP_MINUTES
from syncr_domain.templates import (
    MAX_DURATION_MINUTES,
    MAX_FLEX_BAND_MINUTES,
    MIN_DURATION_MINUTES,
    BindingTarget,
    EntryField,
    EntrySpan,
    TemplateEntryError,
    TemplateEntryKind,
    WeekPattern,
    WeekPatternIncomplete,
)
from syncr_domain.weeks import Weekday

WEEKDAY_SHAPE = uuid4()
WEEKEND_SHAPE = uuid4()
UNMAPPED_SHAPE = uuid4()

WORKING_WEEK = frozenset(
    {Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY}
)


def a_full_mapping() -> dict[Weekday, UUID]:
    return {
        weekday: WEEKDAY_SHAPE if weekday in WORKING_WEEK else WEEKEND_SHAPE for weekday in Weekday
    }


class TestTheVocabularies:
    def test_an_entry_is_concrete_or_a_slot_and_nothing_else(self) -> None:
        # The wire values, the stored values, and the check constraint all read these two.
        assert [kind.value for kind in TemplateEntryKind] == ["concrete", "slot"]

    def test_a_binding_names_the_table_it_points_at(self) -> None:
        # A routine and a habit are separate tables with no shared parent, so the identifier
        # alone does not say which one to read.
        assert [target.value for target in BindingTarget] == ["routine", "habit"]

    def test_no_cadence_vocabulary_exists_here(self) -> None:
        # Cadence lives on habits. A period, an interval, or a repeat named here would be the
        # fourth concept the three above exist to avoid.
        exported = set(dir(TemplateEntryKind)) | set(dir(BindingTarget))

        assert not any("cadence" in name.lower() or "period" in name.lower() for name in exported)


class TestTheWeekPattern:
    def test_a_mapping_of_all_seven_weekdays_is_a_pattern(self) -> None:
        pattern = WeekPattern(a_full_mapping())

        assert pattern.day_type(Weekday.MONDAY) == WEEKDAY_SHAPE
        assert pattern.day_type(Weekday.SUNDAY) == WEEKEND_SHAPE

    @pytest.mark.parametrize(
        "left_out",
        [Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.SUNDAY],
        ids=["the first", "one in the middle", "the last"],
    )
    def test_a_partial_mapping_is_not_a_pattern(self, left_out: Weekday) -> None:
        partial = {
            weekday: day_type
            for weekday, day_type in a_full_mapping().items()
            if weekday != left_out
        }

        with pytest.raises(WeekPatternIncomplete, match=left_out.value):
            WeekPattern(partial)

    def test_an_empty_mapping_names_every_weekday_it_is_missing(self) -> None:
        # The rejection is what the editor renders, so it has to say which rows to fill in
        # rather than that something was wrong.
        with pytest.raises(WeekPatternIncomplete) as rejected:
            WeekPattern({})

        assert all(weekday.value in str(rejected.value) for weekday in Weekday)

    def test_a_pattern_cannot_be_changed_after_its_rule_was_checked(self) -> None:
        # The copy is what makes the check durable: without it, a caller holding the mapping
        # could remove a weekday from a pattern that had already been accepted.
        offered = a_full_mapping()
        pattern = WeekPattern(offered)

        del offered[Weekday.MONDAY]

        assert pattern.day_type(Weekday.MONDAY) == WEEKDAY_SHAPE

    def test_it_covers_a_day_type_some_weekday_uses(self) -> None:
        pattern = WeekPattern(a_full_mapping())

        assert pattern.covers(WEEKDAY_SHAPE)
        assert pattern.covers(WEEKEND_SHAPE)

    def test_it_does_not_cover_a_day_type_no_weekday_uses(self) -> None:
        # The control. A shape whose day type nothing maps changes no week, and without this
        # half "bump when the pattern covers it" and "bump always" are the same rule.
        pattern = WeekPattern(a_full_mapping())

        assert not pattern.covers(UNMAPPED_SHAPE)


class TestTheEntrySpan:
    def test_a_span_on_the_grid_is_accepted(self) -> None:
        span = EntrySpan(target_time=time(7, 45), duration_minutes=45, flex_band_minutes=30)

        assert span.duration_minutes == 45

    @pytest.mark.parametrize(
        "target_time",
        [time(7, 5), time(7, 50), time(7, 0, 30)],
        ids=["five past", "ten to", "half a minute past"],
    )
    def test_a_target_time_off_the_grid_is_refused_and_names_its_field(
        self, target_time: time
    ) -> None:
        with pytest.raises(TemplateEntryError) as refused:
            EntrySpan(target_time=target_time, duration_minutes=30, flex_band_minutes=0)

        assert refused.value.field == EntryField.TARGET_TIME
        assert "quarter hour" in str(refused.value)

    def test_a_target_time_carrying_a_zone_is_refused(self) -> None:
        # A target time is wall time: 07:00 means 07:00 wherever the user is. The column that
        # stores one holds no offset, so an offset offered here would be dropped by the write
        # rather than honored, and the entry would materialize at a different instant than the
        # caller asked for.
        with pytest.raises(TemplateEntryError) as refused:
            EntrySpan(target_time=time(7, 0, tzinfo=UTC), duration_minutes=30, flex_band_minutes=0)

        assert refused.value.field == EntryField.TARGET_TIME
        assert "names no zone" in str(refused.value)

    @pytest.mark.parametrize("duration", [20, 50, 1425 + 15 + 5])
    def test_a_duration_that_is_not_whole_steps_is_refused(self, duration: int) -> None:
        with pytest.raises(TemplateEntryError) as refused:
            EntrySpan(target_time=time(7, 0), duration_minutes=duration, flex_band_minutes=0)

        assert refused.value.field == EntryField.DURATION

    @pytest.mark.parametrize(
        "duration",
        [0, MIN_DURATION_MINUTES - SNAP_MINUTES, MAX_DURATION_MINUTES + SNAP_MINUTES],
        ids=["no span at all", "below one step", "longer than a day"],
    )
    def test_a_duration_outside_its_bounds_is_refused(self, duration: int) -> None:
        with pytest.raises(TemplateEntryError) as refused:
            EntrySpan(target_time=time(7, 0), duration_minutes=duration, flex_band_minutes=0)

        assert refused.value.field == EntryField.DURATION

    @pytest.mark.parametrize(
        "duration",
        [MIN_DURATION_MINUTES, MAX_DURATION_MINUTES],
        ids=["one step", "a whole day"],
    )
    def test_a_duration_at_either_bound_is_accepted(self, duration: int) -> None:
        # The control at both ends: the rejections above have to distinguish rather than refuse
        # everything near the edge.
        assert (
            EntrySpan(
                target_time=time(7, 0), duration_minutes=duration, flex_band_minutes=0
            ).duration_minutes
            == duration
        )

    @pytest.mark.parametrize("band", [-1, MAX_FLEX_BAND_MINUTES + 1])
    def test_a_band_outside_its_bounds_is_refused(self, band: int) -> None:
        with pytest.raises(TemplateEntryError) as refused:
            EntrySpan(target_time=time(7, 0), duration_minutes=30, flex_band_minutes=band)

        assert refused.value.field == EntryField.FLEX_BAND

    @pytest.mark.parametrize("band", [0, 5, MAX_FLEX_BAND_MINUTES])
    def test_a_band_inside_its_bounds_is_accepted_whether_or_not_it_is_a_whole_step(
        self, band: int
    ) -> None:
        # A band bounds a shift rather than being one, and the shift is a placement, which
        # lands on the grid because every placement does. So five minutes is a legal band that
        # permits no shift, not an error.
        span = EntrySpan(target_time=time(7, 0), duration_minutes=30, flex_band_minutes=band)

        assert span.flex_band_minutes == band
