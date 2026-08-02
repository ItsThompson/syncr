"""ISO week identity and week-span derivation across transitions and travel."""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest

from syncr_domain.weeks import IsoWeek, IsoWeekError, week_span
from syncr_domain.zones import TravelOverride, ZoneProfile

LONDON = "Europe/London"
TOKYO = "Asia/Tokyo"

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

    def test_it_orders_chronologically(self) -> None:
        assert sorted([IsoWeek(2027, 1), IsoWeek(2026, 13), IsoWeek(2026, 7)]) == [
            IsoWeek(2026, 7),
            IsoWeek(2026, 13),
            IsoWeek(2027, 1),
        ]


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
