"""Zone resolution and the two daylight-saving rules.

Every DST assertion here names ``Europe/London`` and a real 2026 transition date. No
offset is mocked: a mocked offset would assert what this module was written to
believe rather than what the tz database says.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, available_timezones

import pytest

from syncr_domain.errors import DomainError
from syncr_domain.zones import (
    MAX_ZONE_KEY_LENGTH,
    OverlappingTravelError,
    TravelOverride,
    UnknownZoneError,
    ZoneError,
    ZoneProfile,
    active_zone,
    resolve_zone,
    to_instant,
)

if TYPE_CHECKING:
    from collections.abc import Callable

LONDON = "Europe/London"
TOKYO = "Asia/Tokyo"

SPRING_FORWARD = date(2026, 3, 29)  # 01:00 GMT jumps to 02:00 BST
FALL_BACK = date(2026, 10, 25)  # 02:00 BST repeats as 01:00 GMT

BST = timezone(timedelta(hours=1))


class TestResolveZone:
    def test_a_real_zone_resolves(self) -> None:
        assert resolve_zone(LONDON) == ZoneInfo(LONDON)

    @pytest.mark.parametrize(
        "unknown",
        [
            "Europe/Lundon",
            "",
            "GMT+1",
            "../etc/passwd",
            # A directory in the tz tree rather than a zone. zoneinfo reports this by
            # failing to read the path, not by reporting a missing key, and a user typing
            # a continent into a zone field produces it.
            "Europe",
            "America",
            "US",
            # Longer than any filename the platform will take, so the read fails before
            # the key can be looked up at all.
            "Europe/" + "L" * 300,
        ],
    )
    def test_an_unknown_zone_is_rejected(self, unknown: str) -> None:
        with pytest.raises(UnknownZoneError, match="names no IANA"):
            resolve_zone(unknown)

    @pytest.mark.parametrize("unknown", ["Europe", "Europe/" + "L" * 300])
    def test_every_rejection_a_boundary_sees_is_a_domain_error(self, unknown: str) -> None:
        """The boundary accepts a zone from the wire, so a rejection that escapes
        `DomainError` reaches the client as a 500 rather than a stated refusal."""
        entry_points: list[Callable[[], object]] = [
            lambda: resolve_zone(unknown),
            lambda: to_instant(time(9, 0), date(2026, 2, 1), unknown),
            lambda: TravelOverride(date(2026, 2, 1), date(2026, 2, 2), unknown),
            lambda: ZoneProfile(unknown),
        ]

        for entry_point in entry_points:
            with pytest.raises(DomainError):
                entry_point()

    def test_a_directory_shaped_rejection_carries_no_filesystem_path(self) -> None:
        """The leaked IsADirectoryError named the tz database's path on disk, and this
        message reaches the wire as the stated reason."""
        with pytest.raises(UnknownZoneError) as rejected:
            resolve_zone("Europe")

        assert "/" not in str(rejected.value)

    def test_the_length_bound_rejects_no_zone_the_database_ships(self) -> None:
        """The control on the bound: it must reject nothing real. Over every key rather
        than a sample, because the bound is the only shape rule in `resolve_zone`."""
        keys = available_timezones()

        assert len(keys) > 100, "the tz database looks unreadable, so this proves nothing"
        assert max(len(key) for key in keys) <= MAX_ZONE_KEY_LENGTH


class TestSpringForward:
    """A local time inside the gap shifts forward by the gap length."""

    def test_the_gap_is_real_on_this_date(self) -> None:
        """The control. Without it, the rule below could be asserted about a
        date where nothing happens, and pass for the wrong reason."""
        before = to_instant(time(0, 30), SPRING_FORWARD, LONDON)
        after = to_instant(time(2, 30), SPRING_FORWARD, LONDON)

        assert after - before == timedelta(hours=1)
        assert before.astimezone(ZoneInfo(LONDON)).utcoffset() == timedelta(0)
        assert after.astimezone(ZoneInfo(LONDON)).utcoffset() == timedelta(hours=1)

    def test_a_nonexistent_local_time_shifts_forward_by_the_gap(self) -> None:
        resolved = to_instant(time(1, 30), SPRING_FORWARD, LONDON)

        assert resolved == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
        assert resolved.astimezone(ZoneInfo(LONDON)) == datetime(2026, 3, 29, 2, 30, tzinfo=BST)

    def test_the_local_reading_is_the_requested_time_plus_the_gap(self) -> None:
        gap_length = timedelta(hours=1)
        requested = time(1, 30)

        local = to_instant(requested, SPRING_FORWARD, LONDON).astimezone(ZoneInfo(LONDON))

        assert local.replace(tzinfo=None) - gap_length == datetime.combine(
            SPRING_FORWARD, requested
        )

    def test_it_names_the_instant_the_pre_gap_offset_would_have(self) -> None:
        assert to_instant(time(1, 30), SPRING_FORWARD, LONDON) == datetime.combine(
            SPRING_FORWARD, time(1, 30), tzinfo=UTC
        )

    def test_the_frame_keeps_its_order_through_the_gap(self) -> None:
        frame = [time(0, 30), time(1, 30), time(3, 30)]

        resolved = [to_instant(target, SPRING_FORWARD, LONDON) for target in frame]

        assert resolved == sorted(resolved)

    def test_two_target_times_straddling_the_gap_resolve_to_one_instant(self) -> None:
        """The rule is a shift, not a bijection, so the mapping is not injective here.

        Pinned rather than left incidental: a frame holding both a 01:30 and a 02:30
        routine gets two occurrences starting together, and a caller needing them
        distinct must separate them. A change that made the mapping injective would
        break the stated spring-forward rule, so it fails here rather than quietly
        altering the frame.
        """
        inside_the_gap = to_instant(time(1, 30), SPRING_FORWARD, LONDON)
        after_the_gap = to_instant(time(2, 30), SPRING_FORWARD, LONDON)

        assert inside_the_gap == after_the_gap == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)

    def test_times_clear_of_the_gap_collide_with_nothing(self) -> None:
        """The control: the collision belongs to the gap, not to the mapping."""
        morning = [time(0, 30), time(3, 30), time(4, 30)]

        resolved = [to_instant(target, SPRING_FORWARD, LONDON) for target in morning]

        assert len(set(resolved)) == len(morning)


class TestFallBack:
    """An ambiguous local time takes the first occurrence, the pre-transition offset."""

    def test_the_local_time_is_really_ambiguous_on_this_date(self) -> None:
        """The control: the two readings of 01:30 are an hour apart."""
        naive = datetime.combine(FALL_BACK, time(1, 30), tzinfo=ZoneInfo(LONDON))

        first = naive.replace(fold=0).astimezone(UTC)
        second = naive.replace(fold=1).astimezone(UTC)

        assert second - first == timedelta(hours=1)

    def test_an_ambiguous_local_time_takes_the_earlier_offset(self) -> None:
        resolved = to_instant(time(1, 30), FALL_BACK, LONDON)

        assert resolved == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
        assert resolved.astimezone(ZoneInfo(LONDON)).utcoffset() == timedelta(hours=1)

    def test_it_is_not_the_later_occurrence(self) -> None:
        later = datetime.combine(FALL_BACK, time(1, 30), tzinfo=ZoneInfo(LONDON)).replace(fold=1)

        assert to_instant(time(1, 30), FALL_BACK, LONDON) != later.astimezone(UTC)

    def test_a_wall_time_carrying_fold_still_takes_the_first_occurrence(self) -> None:
        """`datetime.combine` copies `fold` from the `time`, so the rule is unconditional
        only because `to_instant` normalizes it. Without that normalization this input
        would return the later occurrence, which is the rule inverted, and no other test
        would notice.
        """
        plain = to_instant(time(1, 30), FALL_BACK, LONDON)

        assert to_instant(time(1, 30, fold=1), FALL_BACK, LONDON) == plain
        assert plain == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)

    def test_the_later_occurrence_is_a_different_instant(self) -> None:
        """The control on the test above: an hour apart, so ignoring `fold` and honoring
        it are distinguishable outcomes."""
        naive = datetime.combine(FALL_BACK, time(1, 30), tzinfo=ZoneInfo(LONDON))

        assert naive.replace(fold=1).astimezone(UTC) == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)

    def test_the_frame_keeps_its_order_and_distinctness_through_the_repeat(self) -> None:
        """Unlike the gap, this rule maps distinct wall times to distinct instants:
        taking the earlier offset moves nothing onto another wall time's instant."""
        frame = [time(0, 30), time(1, 30), time(3, 0)]

        resolved = [to_instant(target, FALL_BACK, LONDON) for target in frame]

        assert resolved == sorted(resolved)
        assert len(set(resolved)) == len(frame)


class TestToInstant:
    def test_an_ordinary_date_maps_without_a_shift(self) -> None:
        assert to_instant(time(1, 30), date(2026, 6, 15), LONDON) == datetime(
            2026, 6, 15, 0, 30, tzinfo=UTC
        )
        assert to_instant(time(9, 0), date(2026, 1, 15), LONDON) == datetime(
            2026, 1, 15, 9, 0, tzinfo=UTC
        )

    def test_the_same_wall_time_is_a_different_instant_in_another_zone(self) -> None:
        on = date(2026, 1, 15)

        assert to_instant(time(9, 0), on, TOKYO) == datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
        assert to_instant(time(9, 0), on, LONDON) != to_instant(time(9, 0), on, TOKYO)

    def test_a_wall_time_carrying_a_zone_is_rejected(self) -> None:
        with pytest.raises(ZoneError, match="a wall time names none"):
            to_instant(time(9, 0, tzinfo=UTC), date(2026, 1, 15), LONDON)

    def test_a_datetime_in_place_of_a_date_is_rejected(self) -> None:
        with pytest.raises(ZoneError, match="silently drop its time"):
            to_instant(time(9, 0), datetime(2026, 1, 15, 18, 0, tzinfo=UTC), LONDON)

    def test_an_unknown_zone_is_rejected(self) -> None:
        with pytest.raises(UnknownZoneError):
            to_instant(time(9, 0), date(2026, 1, 15), "Mars/Olympus_Mons")


class TestTravelOverride:
    def test_it_covers_both_of_its_end_dates(self) -> None:
        override = TravelOverride(date(2026, 2, 11), date(2026, 2, 20), TOKYO)

        assert override.covers(date(2026, 2, 11))
        assert override.covers(date(2026, 2, 20))
        assert not override.covers(date(2026, 2, 10))
        assert not override.covers(date(2026, 2, 21))

    def test_a_single_day_override_is_allowed(self) -> None:
        override = TravelOverride(date(2026, 2, 11), date(2026, 2, 11), TOKYO)

        assert override.covers(date(2026, 2, 11))

    def test_an_end_before_its_start_is_rejected(self) -> None:
        with pytest.raises(ZoneError, match="start_date <= end_date"):
            TravelOverride(date(2026, 2, 20), date(2026, 2, 11), TOKYO)

    def test_an_unknown_zone_is_rejected(self) -> None:
        with pytest.raises(UnknownZoneError):
            TravelOverride(date(2026, 2, 11), date(2026, 2, 20), "Nowhere/Fictional")

    def test_two_that_abut_exactly_do_not_overlap(self) -> None:
        earlier = TravelOverride(date(2026, 2, 11), date(2026, 2, 20), TOKYO)
        later = TravelOverride(date(2026, 2, 21), date(2026, 2, 28), LONDON)

        assert not earlier.overlaps(later)
        assert not later.overlaps(earlier)

    def test_a_shared_date_is_an_overlap(self) -> None:
        earlier = TravelOverride(date(2026, 2, 11), date(2026, 2, 20), TOKYO)
        later = TravelOverride(date(2026, 2, 20), date(2026, 2, 28), LONDON)

        assert earlier.overlaps(later)
        assert later.overlaps(earlier)


class TestZoneProfile:
    def test_it_sorts_its_overrides(self) -> None:
        later = TravelOverride(date(2026, 5, 1), date(2026, 5, 8), TOKYO)
        earlier = TravelOverride(date(2026, 2, 11), date(2026, 2, 20), TOKYO)

        profile = ZoneProfile(LONDON, (later, earlier))

        assert profile.travel_overrides == (earlier, later)

    def test_abutting_overrides_are_allowed(self) -> None:
        profile = ZoneProfile(
            LONDON,
            (
                TravelOverride(date(2026, 2, 11), date(2026, 2, 20), TOKYO),
                TravelOverride(date(2026, 2, 21), date(2026, 2, 28), "America/New_York"),
            ),
        )

        assert active_zone(profile, date(2026, 2, 20)) == TOKYO
        assert active_zone(profile, date(2026, 2, 21)) == "America/New_York"

    @pytest.mark.parametrize(
        ("label", "second"),
        [
            ("a shared end date", TravelOverride(date(2026, 2, 20), date(2026, 2, 28), TOKYO)),
            ("full containment", TravelOverride(date(2026, 2, 12), date(2026, 2, 14), TOKYO)),
            ("an identical range", TravelOverride(date(2026, 2, 11), date(2026, 2, 20), TOKYO)),
        ],
    )
    def test_overlapping_overrides_are_rejected(self, label: str, second: TravelOverride) -> None:
        first = TravelOverride(date(2026, 2, 11), date(2026, 2, 20), "America/New_York")

        with pytest.raises(OverlappingTravelError, match="cover a common date"):
            ZoneProfile(LONDON, (first, second))

    def test_an_unknown_home_zone_is_rejected(self) -> None:
        with pytest.raises(UnknownZoneError):
            ZoneProfile("Europe/Lundon")


class TestActiveZone:
    def test_the_home_zone_applies_when_nothing_overrides_it(self) -> None:
        assert active_zone(ZoneProfile(LONDON), date(2026, 2, 11)) == LONDON

    def test_an_override_wins_within_its_range(self) -> None:
        profile = ZoneProfile(
            LONDON, (TravelOverride(date(2026, 2, 11), date(2026, 2, 20), TOKYO),)
        )

        assert active_zone(profile, date(2026, 2, 10)) == LONDON
        assert active_zone(profile, date(2026, 2, 11)) == TOKYO
        assert active_zone(profile, date(2026, 2, 20)) == TOKYO
        assert active_zone(profile, date(2026, 2, 21)) == LONDON

    def test_a_week_crossing_a_travel_boundary_resolves_two_zones(self) -> None:
        profile = ZoneProfile(
            LONDON, (TravelOverride(date(2026, 2, 12), date(2026, 2, 20), TOKYO),)
        )
        monday = date(2026, 2, 9)

        resolved = [active_zone(profile, monday + timedelta(days=offset)) for offset in range(7)]

        assert resolved == [LONDON, LONDON, LONDON, TOKYO, TOKYO, TOKYO, TOKYO]
        assert len(set(resolved)) == 2
