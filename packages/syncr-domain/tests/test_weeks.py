"""ISO week identity and week-span derivation across transitions and travel."""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest

from syncr_domain.weeks import (
    IsoWeek,
    IsoWeekError,
    Weekday,
    active_zone_by_date,
    local_days,
    longest_consecutive_run,
    week_span,
)
from syncr_domain.zones import TravelOverride, ZoneProfile

LONDON = "Europe/London"
TOKYO = "Asia/Tokyo"
# The eastern extreme, +14:00. Paired with `Etc/GMT+12` at -12:00 it gives a 26-hour offset
# difference, which is more than a date is long.
KIRITIMATI = "Pacific/Kiritimati"

HOME = ZoneProfile(LONDON)


class TestIsoWeekIdentity:
    @pytest.mark.parametrize(
        ("identifier", "expected"),
        [
            ("2026-W07", IsoWeek(2026, 7)),
            ("2026-W13", IsoWeek(2026, 13)),
            ("2026-W53", IsoWeek(2026, 53)),
        ],
    )
    def test_it_parses_the_wire_identifier(self, identifier: str, expected: IsoWeek) -> None:
        assert IsoWeek.parse(identifier) == expected

    @pytest.mark.parametrize(
        "malformed", ["2026-W7", "2026W07", "26-W07", "2026-w07", "2026-W07 ", "", "week"]
    )
    def test_a_malformed_identifier_is_rejected(self, malformed: str) -> None:
        with pytest.raises(IsoWeekError, match="ISO week identifier"):
            IsoWeek.parse(malformed)

    @pytest.mark.parametrize(("year", "week"), [(2026, 0), (2026, 54), (2025, 53), (2026, -1)])
    def test_a_week_its_year_does_not_have_is_rejected(self, year: int, week: int) -> None:
        with pytest.raises(IsoWeekError, match="is not an ISO week"):
            IsoWeek(year, week)

    def test_a_year_with_53_weeks_accepts_the_53rd(self) -> None:
        assert IsoWeek(2026, 53).monday() == date(2026, 12, 28)

    def test_it_renders_zero_padded(self) -> None:
        assert str(IsoWeek(2026, 7)) == "2026-W07"
        assert str(IsoWeek(2026, 13)) == "2026-W13"

    def test_parsing_reverses_rendering(self) -> None:
        week = IsoWeek(2026, 7)

        assert IsoWeek.parse(str(week)) == week

    def test_monday_is_the_first_day(self) -> None:
        assert IsoWeek(2026, 13).monday() == date(2026, 3, 23)
        assert IsoWeek(2026, 13).monday().isoweekday() == 1

    def test_a_week_is_seven_dates_from_its_monday(self) -> None:
        assert IsoWeek(2026, 13).dates() == (
            date(2026, 3, 23),
            date(2026, 3, 24),
            date(2026, 3, 25),
            date(2026, 3, 26),
            date(2026, 3, 27),
            date(2026, 3, 28),
            date(2026, 3, 29),
        )

    def test_the_transition_week_still_holds_seven_dates(self) -> None:
        """A week is seven dates whatever its length in minutes.

        The spring-forward week is 167 hours and the fall-back week is 169, and a per-date
        collection covers seven days in both. That is why this needs no zone: how long a week
        is, is ``week_span``'s question and it does need one.
        """
        for iso_week in (IsoWeek(2026, 13), IsoWeek(2026, 43)):
            assert len(iso_week.dates()) == len(Weekday)

    def test_the_dates_run_monday_to_sunday(self) -> None:
        assert [day.isoweekday() for day in IsoWeek(2026, 7).dates()] == [1, 2, 3, 4, 5, 6, 7]

    def test_the_dates_of_consecutive_weeks_abut(self) -> None:
        week = IsoWeek(2026, 52)

        assert week.dates()[-1] + timedelta(days=1) == week.following().dates()[0]

    @pytest.mark.parametrize(
        ("on", "expected"),
        [
            (date(2026, 3, 29), IsoWeek(2026, 13)),
            (date(2026, 3, 23), IsoWeek(2026, 13)),
            (date(2026, 10, 25), IsoWeek(2026, 43)),
            # The ISO year runs ahead of the calendar year at the turn.
            (date(2025, 12, 29), IsoWeek(2026, 1)),
            (date(2026, 1, 1), IsoWeek(2026, 1)),
        ],
    )
    def test_it_names_the_week_containing_a_date(self, on: date, expected: IsoWeek) -> None:
        assert IsoWeek.containing(on) == expected

    def test_following_advances_one_week(self) -> None:
        assert IsoWeek(2026, 13).following() == IsoWeek(2026, 14)

    def test_following_rolls_into_the_next_iso_year(self) -> None:
        assert IsoWeek(2026, 53).following() == IsoWeek(2027, 1)

    def test_preceding_steps_back_one_week(self) -> None:
        assert IsoWeek(2026, 14).preceding() == IsoWeek(2026, 13)

    def test_preceding_rolls_into_the_previous_iso_year_at_its_own_length(self) -> None:
        # 2026 is a 53-week ISO year and 2025 is a 52-week one, so neither the week number nor
        # the year decides this on its own: the assembler reads the preceding week to carry a
        # Sunday-night occurrence's overhang, and the first week of a year is the case that
        # would silently read a week that does not exist.
        assert IsoWeek(2027, 1).preceding() == IsoWeek(2026, 53)
        assert IsoWeek(2026, 1).preceding() == IsoWeek(2025, 52)

    def test_a_week_steps_back_to_itself_through_the_week_after_it(self) -> None:
        for iso_week in (IsoWeek(2026, 1), IsoWeek(2026, 13), IsoWeek(2026, 53)):
            assert iso_week.following().preceding() == iso_week

    def test_it_orders_chronologically(self) -> None:
        assert sorted([IsoWeek(2027, 1), IsoWeek(2026, 13), IsoWeek(2026, 7)]) == [
            IsoWeek(2026, 7),
            IsoWeek(2026, 13),
            IsoWeek(2027, 1),
        ]


class TestWeekdays:
    def test_the_seven_weekdays_are_declared_in_iso_order(self) -> None:
        # Load-bearing: the enum's own order is what the week-pattern editor renders and what
        # the rejection message lists, so nothing restates it.
        assert [weekday.value for weekday in Weekday] == [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]

    def test_each_weekday_matches_the_iso_position_of_a_real_date(self) -> None:
        # 2026-W07 runs Monday the 9th to Sunday the 15th of February. Asserted against real
        # dates because a name is only right if it agrees with the calendar.
        monday = IsoWeek(2026, 7).monday()

        for offset, weekday in enumerate(Weekday):
            day = monday + timedelta(days=offset)
            assert day.isoweekday() == offset + 1, weekday


class TestWeekSpan:
    def test_an_ordinary_week_is_168_hours(self) -> None:
        span = week_span(IsoWeek(2026, 10), HOME)

        assert span.total_minutes() == 168 * 60

    def test_the_spring_forward_week_is_167_hours(self) -> None:
        span = week_span(IsoWeek(2026, 13), HOME)

        assert span.total_minutes() == 167 * 60

    def test_the_fall_back_week_is_169_hours(self) -> None:
        span = week_span(IsoWeek(2026, 43), HOME)

        assert span.total_minutes() == 169 * 60

    def test_it_runs_from_local_midnight_to_local_midnight(self) -> None:
        span = week_span(IsoWeek(2026, 13), HOME)
        london_local = span.start.astimezone(ZoneInfo(LONDON))

        assert london_local.date() == date(2026, 3, 23)
        assert (london_local.hour, london_local.minute) == (0, 0)

    def test_a_travel_boundary_mid_week_shortens_the_span_by_the_offset(self) -> None:
        travelling = ZoneProfile(
            LONDON, (TravelOverride(date(2026, 2, 12), date(2026, 2, 20), TOKYO),)
        )

        span = week_span(IsoWeek(2026, 7), travelling)

        # Monday's zone bounds the start, the following Monday's the end: London is
        # nine hours behind Tokyo in February, so the week loses those nine hours.
        assert span.total_minutes() == (168 - 9) * 60
        assert (
            span.start.astimezone(ZoneInfo(LONDON)).strftime("%Y-%m-%d %H:%M") == "2026-02-09 00:00"
        )
        assert span.end.astimezone(ZoneInfo(TOKYO)).strftime("%Y-%m-%d %H:%M") == "2026-02-16 00:00"

    def test_returning_mid_week_lengthens_the_span(self) -> None:
        returning = ZoneProfile(
            TOKYO, (TravelOverride(date(2026, 2, 12), date(2026, 2, 20), LONDON),)
        )

        span = week_span(IsoWeek(2026, 7), returning)

        assert span.total_minutes() == (168 + 9) * 60

    def test_an_override_starting_on_the_monday_governs_from_that_monday(self) -> None:
        monday = IsoWeek(2026, 7).monday()
        from_the_boundary = ZoneProfile(
            LONDON, (TravelOverride(monday, monday + timedelta(days=13), TOKYO),)
        )

        span = week_span(IsoWeek(2026, 7), from_the_boundary)

        assert span == week_span(IsoWeek(2026, 7), ZoneProfile(TOKYO))

    def test_consecutive_spans_abut_exactly(self) -> None:
        spring = week_span(IsoWeek(2026, 13), HOME)
        following = week_span(IsoWeek(2026, 14), HOME)

        assert spring.end == following.start
        assert not spring.overlaps(following)

    @pytest.mark.parametrize(
        ("zone", "week", "minutes"),
        [
            # A two-hour transition, so neither 167 nor 169.
            ("Antarctica/Troll", 13, 166 * 60),
            ("Antarctica/Troll", 43, 170 * 60),
            # A thirty-minute transition, so not a whole number of hours at all.
            ("Australia/Lord_Howe", 40, 167 * 60 + 30),
            ("Australia/Lord_Howe", 14, 168 * 60 + 30),
        ],
    )
    def test_a_transition_that_is_not_an_hour_gives_a_span_outside_the_usual_three(
        self, zone: str, week: int, minutes: int
    ) -> None:
        """167, 168 and 169 are what most weeks are, not a rule the arithmetic enforces.
        A downstream check that enumerates hour counts, or divides by 60, is wrong for
        these zones, so the spans are pinned here rather than left to a reader's
        assumption."""
        span = week_span(IsoWeek(2026, week), ZoneProfile(zone))

        assert span.total_minutes() == minutes


class TestTheZoneEachDayResolves:
    """A week is not one zone, so every shape carrying its wall-time resolutions carries seven."""

    def test_it_answers_for_each_of_the_weeks_seven_dates(self) -> None:
        resolved = active_zone_by_date(IsoWeek(2026, 7), HOME)

        assert list(resolved) == list(IsoWeek(2026, 7).dates())
        assert set(resolved.values()) == {LONDON}

    def test_a_mid_week_travel_override_gives_the_week_two_zones(self) -> None:
        # Thursday to Sunday abroad: the days either side of the boundary resolve their wall times
        # against different offsets, which is the case a single zone per week reads wrongly.
        profile = ZoneProfile(
            LONDON,
            (TravelOverride(date(2026, 2, 12), date(2026, 2, 15), TOKYO),),
        )

        resolved = active_zone_by_date(IsoWeek(2026, 7), profile)

        assert resolved[date(2026, 2, 11)] == LONDON
        assert resolved[date(2026, 2, 12)] == TOKYO
        assert resolved[date(2026, 2, 15)] == TOKYO

    def test_a_span_that_names_the_travel_zone_still_resolves_the_home_days_at_home(self) -> None:
        # The span's two Mondays and the days inside it are separate questions, so an override
        # covering the Monday must not change what Wednesday resolves.
        profile = ZoneProfile(
            LONDON,
            (TravelOverride(date(2026, 2, 9), date(2026, 2, 10), TOKYO),),
        )

        resolved = active_zone_by_date(IsoWeek(2026, 7), profile)

        assert resolved[date(2026, 2, 9)] == TOKYO
        assert resolved[date(2026, 2, 11)] == LONDON


class TestTheLocalDaysOfAWeek:
    """A per-day figure is measured against the day the user had, not a 24-hour slice."""

    def test_an_ordinary_week_is_seven_days_of_twenty_four_hours_covering_the_whole_span(
        self,
    ) -> None:
        week = IsoWeek(2026, 7)
        span = week_span(week, HOME)

        days = local_days(week, active_zone_by_date(week, HOME), span)

        assert [day.on for day in days] == list(week.dates())
        assert [day.interval.total_minutes() for day in days] == [24 * 60] * 7
        assert days[0].interval.start == span.start
        assert days[-1].interval.end == span.end

    def test_the_spring_forward_date_is_twenty_three_hours_and_its_neighbours_are_not(self) -> None:
        # The whole reason a per-day figure cannot slice the span into equal parts: one date of
        # this week is an hour shorter than the others and the cap for that day is measured on it.
        week = IsoWeek(2026, 13)
        span = week_span(week, HOME)

        days = local_days(week, active_zone_by_date(week, HOME), span)

        lengths = {day.on: day.interval.total_minutes() for day in days}
        assert lengths[date(2026, 3, 29)] == 23 * 60
        assert lengths[date(2026, 3, 28)] == 24 * 60
        assert lengths[date(2026, 3, 23)] == 24 * 60
        assert sum(lengths.values()) == span.total_minutes()

    def test_the_fall_back_date_is_twenty_five_hours(self) -> None:
        week = IsoWeek(2026, 43)
        span = week_span(week, HOME)

        days = local_days(week, active_zone_by_date(week, HOME), span)

        lengths = {day.on: day.interval.total_minutes() for day in days}
        assert lengths[date(2026, 10, 25)] == 25 * 60
        assert sum(lengths.values()) == span.total_minutes()

    def test_a_mid_week_move_east_shortens_the_date_the_boundary_falls_on(self) -> None:
        # Thursday onwards in Tokyo, nine hours ahead: Thursday's own midnight arrives nine hours
        # earlier than London's would, so Wednesday is fifteen hours long where the user was.
        week = IsoWeek(2026, 7)
        profile = ZoneProfile(
            LONDON, (TravelOverride(date(2026, 2, 12), date(2026, 2, 15), TOKYO),)
        )
        span = week_span(week, profile)

        days = local_days(week, active_zone_by_date(week, profile), span)

        lengths = {day.on: day.interval.total_minutes() for day in days}
        assert lengths[date(2026, 2, 11)] == 15 * 60
        assert lengths[date(2026, 2, 12)] == 24 * 60
        assert sum(lengths.values()) == span.total_minutes()

    def test_a_move_between_the_extreme_offsets_drops_the_date_it_cannot_bound(self) -> None:
        # Twenty-six hours of offset is more than a date is long, so Friday's midnight lands
        # BEFORE Thursday's and the pair does not run forward. The date is dropped rather than
        # reordered, and the dates around it still answer.
        week = IsoWeek(2026, 7)
        profile = ZoneProfile(
            "Etc/GMT+12", (TravelOverride(date(2026, 2, 13), date(2026, 2, 15), KIRITIMATI),)
        )
        span = week_span(week, profile)

        days = local_days(week, active_zone_by_date(week, profile), span)

        assert date(2026, 2, 12) not in {day.on for day in days}
        assert date(2026, 2, 13) in {day.on for day in days}
        assert len(days) == 6

    def test_no_day_reaches_outside_the_week_it_belongs_to(self) -> None:
        # A per-day figure taken over these may not charge a minute the week does not hold, so the
        # bound is stated here rather than at each reader.
        week = IsoWeek(2026, 7)
        profile = ZoneProfile(
            LONDON, (TravelOverride(date(2026, 2, 15), date(2026, 2, 15), KIRITIMATI),)
        )
        span = week_span(week, profile)

        days = local_days(week, active_zone_by_date(week, profile), span)

        assert all(span.start <= day.interval.start for day in days)
        assert all(day.interval.end <= span.end for day in days)

    def test_a_day_whose_own_midnight_falls_before_the_week_opens_starts_where_the_week_does(
        self,
    ) -> None:
        # The clip is not decoration. Moving east on the week's SECOND date puts that date's own
        # midnight two hours before the week opens, so the first date cannot be bounded at all and
        # the second would otherwise charge two hours the week does not hold.
        week = IsoWeek(2026, 7)
        profile = ZoneProfile(
            "Etc/GMT+12", (TravelOverride(date(2026, 2, 10), date(2026, 2, 15), KIRITIMATI),)
        )
        span = week_span(week, profile)

        days = local_days(week, active_zone_by_date(week, profile), span)

        assert date(2026, 2, 9) not in {day.on for day in days}
        assert days[0].on == date(2026, 2, 10)
        assert days[0].interval.start == span.start
        assert days[0].interval.total_minutes() == 22 * 60
        # The last date runs to the span's end, which the FOLLOWING Monday's zone bounds: the
        # override ends on the 15th, so that date is fifty hours long where the user was. The
        # arithmetic is exposed rather than smoothed, because which instant closes the week is the
        # span's own statement and not this function's to correct.
        assert days[-1].interval.end == span.end
        assert sum(day.interval.total_minutes() for day in days) == span.total_minutes()


class TestTheLongestConsecutiveRun:
    """The one statement of "n consecutive weeks", which two raises are counted with.

    A repeated pin becomes a template promotion and an item skipped week after week is escalated.
    Both count a run, so both read this, and a second implementation is how one surface comes to say
    four weeks while the other says three about the same behaviour.
    """

    def test_an_unbroken_run_is_its_whole_length(self) -> None:
        weeks = [IsoWeek(2026, number) for number in (7, 8, 9, 10)]

        assert longest_consecutive_run(weeks) == tuple(weeks)

    def test_a_gap_starts_a_new_run(self) -> None:
        weeks = [IsoWeek(2026, number) for number in (2, 7, 8, 9, 10, 20)]

        assert longest_consecutive_run(weeks) == tuple(
            IsoWeek(2026, number) for number in (7, 8, 9, 10)
        )

    def test_weeks_with_a_gap_between_each_are_a_run_of_one(self) -> None:
        # Weeks 7, 9 and 11 are a repeated behaviour rather than a run, and counting three of them
        # would report a pattern from three unrelated weeks.
        weeks = [IsoWeek(2026, number) for number in (7, 9, 11)]

        assert longest_consecutive_run(weeks) == (IsoWeek(2026, 7),)

    def test_the_earliest_run_wins_a_tie(self) -> None:
        weeks = [IsoWeek(2026, number) for number in (2, 3, 20, 21)]

        assert longest_consecutive_run(weeks) == (IsoWeek(2026, 2), IsoWeek(2026, 3))

    def test_a_run_across_a_year_boundary_is_a_run(self) -> None:
        # 2026 holds 53 weeks, so 2026-W53 is followed by 2027-W01 and neither the week number nor
        # the ISO year alone decides the answer.
        weeks = [IsoWeek(2026, 52), IsoWeek(2026, 53), IsoWeek(2027, 1)]

        assert longest_consecutive_run(weeks) == tuple(weeks)

    def test_a_year_with_52_weeks_still_runs_into_the_next(self) -> None:
        weeks = [IsoWeek(2025, 51), IsoWeek(2025, 52), IsoWeek(2026, 1)]

        assert longest_consecutive_run(weeks) == tuple(weeks)

    def test_a_week_contributing_twice_is_one_week_of_evidence(self) -> None:
        weeks = [IsoWeek(2026, 7), IsoWeek(2026, 7), IsoWeek(2026, 8)]

        assert longest_consecutive_run(weeks) == (IsoWeek(2026, 7), IsoWeek(2026, 8))

    def test_the_order_the_caller_read_them_in_does_not_matter(self) -> None:
        assert longest_consecutive_run([IsoWeek(2026, 9), IsoWeek(2026, 7), IsoWeek(2026, 8)]) == (
            IsoWeek(2026, 7),
            IsoWeek(2026, 8),
            IsoWeek(2026, 9),
        )

    def test_nothing_is_a_run_of_nothing(self) -> None:
        assert longest_consecutive_run([]) == ()
