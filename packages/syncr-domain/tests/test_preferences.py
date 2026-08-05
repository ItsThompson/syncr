"""The Preference's five rules, and the resolution that picks one out of a chain.

Three of them are asserted from both ends rather than only from the side that rejects, because
a rule stated once reads as a rejection nobody can distinguish from a type error.

``hard`` is asserted absent in three ways: the enum has two members, the string is not one of
them, and no public name in the module spells it. A single membership assertion would go on
passing if a third member arrived under a different spelling, and the exact value list is what
closes that.

The daily cap is asserted on all three owners in one parametrized case, so an Area accepting one
and the two overrides refusing it are the same test rather than two that could drift.

The resolution's own test is the one to read: it asserts that an override with NO ideal duration
resolves to no ideal duration even when its Area declares one. That is the difference between
replacing wholly and merging field by field, and it is the only assertion here that would still
pass if the resolution merged.
"""

from __future__ import annotations

import inspect
from datetime import UTC, time
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

import syncr_domain.preferences as preferences_module
from syncr_domain.preferences import (
    MAX_MAX_PER_DAY_MINUTES,
    MAX_PREFERRED_DURATION_MINUTES,
    MAX_WINDOWS,
    MIN_MAX_PER_DAY_MINUTES,
    MIN_PREFERRED_DURATION_MINUTES,
    LocalTimeWindow,
    Preference,
    PreferenceChainOutOfOrder,
    PreferenceError,
    PreferenceField,
    PreferenceOwner,
    PreferenceOwnerKind,
    PreferenceStrength,
    captured_from_slot,
    preference_in_effect,
)
from syncr_domain.snap import SNAP_MINUTES

if TYPE_CHECKING:
    from collections.abc import Callable

AREA = PreferenceOwner(kind=PreferenceOwnerKind.AREA, id=uuid4())
HABIT = PreferenceOwner(kind=PreferenceOwnerKind.HABIT, id=uuid4())
TASK = PreferenceOwner(kind=PreferenceOwnerKind.TASK, id=uuid4())

EARLY = LocalTimeWindow(start=time(5, 30), end=time(7, 0))
MIDDAY = LocalTimeWindow(start=time(13, 15), end=time(14, 15))


def a_preference(
    owner: PreferenceOwner = AREA,
    *,
    windows: tuple[LocalTimeWindow, ...] = (EARLY,),
    strength: PreferenceStrength = PreferenceStrength.STRONG,
    preferred_duration_minutes: int | None = None,
    max_per_day_minutes: int | None = None,
) -> Preference:
    return Preference(
        owner=owner,
        windows=windows,
        strength=strength,
        preferred_duration_minutes=preferred_duration_minutes,
        max_per_day_minutes=max_per_day_minutes,
    )


class TestP1TheStrengthIsNeverHard:
    def test_exactly_two_strengths_exist(self) -> None:
        # The wire values, the stored values, and the check constraint all read these two.
        assert [strength.value for strength in PreferenceStrength] == ["strong", "soft"]

    def test_hard_is_not_a_strength(self) -> None:
        with pytest.raises(ValueError, match="hard"):
            PreferenceStrength("hard")

    def test_no_public_name_in_the_module_spells_a_hard_strength(self) -> None:
        # The value list above is what stops a THIRD member arriving under any spelling. This
        # is the narrower half: no name here reintroduces the word, so a `HARD_WINDOW` helper
        # or a `hard_strength` constant cannot appear beside two members that look right.
        named = [name for name in dir(preferences_module) if "hard" in name.lower()]

        assert named == []
        assert [strength.name for strength in PreferenceStrength] == ["STRONG", "SOFT"]

    def test_both_strengths_are_accepted_on_a_preference(self) -> None:
        for strength in PreferenceStrength:
            assert a_preference(strength=strength).strength is strength


class TestP3TheDailyCapIsAnAreasAlone:
    def test_an_area_carries_a_cap(self) -> None:
        assert a_preference(AREA, max_per_day_minutes=180).max_per_day_minutes == 180

    @pytest.mark.parametrize("owner", [HABIT, TASK], ids=["habit", "task"])
    def test_an_override_cannot_carry_a_cap(self, owner: PreferenceOwner) -> None:
        # X13, stated over both other owners in one case so the two cannot drift.
        with pytest.raises(PreferenceError) as refused:
            a_preference(owner, max_per_day_minutes=180)

        assert refused.value.field is PreferenceField.MAX_PER_DAY
        assert owner.kind.value in str(refused.value)
        assert "relax" in str(refused.value)

    @pytest.mark.parametrize("owner", [AREA, HABIT, TASK], ids=["area", "habit", "task"])
    def test_every_owner_may_carry_no_cap_at_all(self, owner: PreferenceOwner) -> None:
        assert a_preference(owner).max_per_day_minutes is None

    @pytest.mark.parametrize(
        "minutes", [MIN_MAX_PER_DAY_MINUTES - 1, MAX_MAX_PER_DAY_MINUTES + 1], ids=["under", "over"]
    )
    def test_a_cap_outside_the_bounds_is_refused(self, minutes: int) -> None:
        with pytest.raises(PreferenceError) as refused:
            a_preference(AREA, max_per_day_minutes=minutes)

        assert refused.value.field is PreferenceField.MAX_PER_DAY

    def test_the_floor_is_one_grid_step_because_a_smaller_cap_admits_no_block(self) -> None:
        # Asserted as the derivation rather than as the literal 15, so a retune of the grid
        # moves the bound instead of leaving a second statement of the grid here.
        assert MIN_MAX_PER_DAY_MINUTES == SNAP_MINUTES
        assert a_preference(AREA, max_per_day_minutes=SNAP_MINUTES).max_per_day_minutes == 15

    @pytest.mark.parametrize("minutes", [100, 16, 61, MAX_MAX_PER_DAY_MINUTES - 1])
    def test_a_cap_owes_no_grid_at_all(self, minutes: int) -> None:
        """A cap is a budget figure rather than a geometry, so it lands wherever the user put it.

        Every other case in this class happens to use a multiple of the snap, which left the rule
        stated in prose and asserted nowhere: a snap check added to this field tomorrow would pass
        the whole suite. 100 minutes admits six blocks and says "at most this much", which is what a
        cap is for; the ideal duration is the field that owes the grid, and it is refused off it two
        classes down.

        Ticket 47's Areas screen rests on this: it authors the cap through a plain figure field
        rather than a quarter-hour stepper, and a stepper wrote 105 for a typed 100.
        """
        # A floor on the parametrization: a multiple of the snap here would make the case vacuous.
        assert minutes % SNAP_MINUTES != 0
        assert a_preference(AREA, max_per_day_minutes=minutes).max_per_day_minutes == minutes


class TestP5AnOverrideReplacesWholly:
    def test_an_override_wins_over_its_area(self) -> None:
        area = a_preference(AREA, windows=(EARLY,), strength=PreferenceStrength.STRONG)
        habit = a_preference(HABIT, windows=(MIDDAY,), strength=PreferenceStrength.SOFT)

        assert preference_in_effect(habit, area) is habit

    def test_an_override_that_states_no_ideal_duration_has_none(self) -> None:
        # The assertion that separates replacing wholly from merging field by field. A merge
        # would fill the override's null from the Area's 90 and this would read 90.
        area = a_preference(AREA, windows=(EARLY,), preferred_duration_minutes=90)
        habit = a_preference(HABIT, windows=(MIDDAY,), preferred_duration_minutes=None)

        in_effect = preference_in_effect(habit, area)

        assert in_effect is not None
        assert in_effect.preferred_duration_minutes is None

    def test_an_override_with_no_windows_opts_out_of_its_areas_windows(self) -> None:
        # An empty window list on an override is a statement rather than an omission: this
        # habit has no preferred time even though the rest of its Area does.
        area = a_preference(AREA, windows=(EARLY, MIDDAY))
        habit = a_preference(HABIT, windows=())

        in_effect = preference_in_effect(habit, area)

        assert in_effect is not None
        assert in_effect.windows == ()

    def test_an_owner_with_no_override_inherits_its_area(self) -> None:
        area = a_preference(AREA)

        assert preference_in_effect(None, area) is area

    def test_an_owner_whose_area_declares_nothing_has_no_preference(self) -> None:
        assert preference_in_effect(None, None) is None

    def test_an_areas_own_preference_is_a_chain_of_one(self) -> None:
        area = a_preference(AREA)

        assert preference_in_effect(area) is area

    def test_exactly_one_preference_is_in_effect_for_every_shape_of_chain(self) -> None:
        # The criterion's own claim: a chain resolves to one preference, never two merged and
        # never a list. Stated over all four shapes a chain can take.
        area = a_preference(AREA)
        habit = a_preference(HABIT)
        chains = [(habit, area), (habit, None), (None, area), (None, None)]

        resolved = [preference_in_effect(*chain) for chain in chains]

        assert resolved == [habit, habit, area, None]
        assert all(found is None or isinstance(found, Preference) for found in resolved)

    def test_an_areas_preference_ahead_of_an_override_is_refused(self) -> None:
        # A caller that ordered the chain the other way would make every override inert, and
        # nothing downstream would report it: the windows would simply stop being read.
        area = a_preference(AREA)
        habit = a_preference(HABIT)

        with pytest.raises(PreferenceChainOutOfOrder, match="position 0 of 2"):
            preference_in_effect(area, habit)

    def test_the_source_is_the_owner_the_resolution_returns(self) -> None:
        # Where a preference came from is the preference's own owner, so a read model does not
        # need a second field for it and cannot report one that disagrees.
        habit = a_preference(HABIT)

        in_effect = preference_in_effect(habit, a_preference(AREA))

        assert in_effect is not None
        assert in_effect.owner == HABIT


class TestP2CaptureFromASlotIsAlwaysSoft:
    def test_the_captured_preference_is_soft(self) -> None:
        captured = captured_from_slot(owner=HABIT, windows=(MIDDAY,))

        assert captured.strength is PreferenceStrength.SOFT

    def test_there_is_no_strength_to_pass(self) -> None:
        # The enforcement rather than the observation: a caller cannot ask for a strong window,
        # so a pin made by dragging a block cannot fabricate a training label.
        assert "strength" not in inspect.signature(captured_from_slot).parameters

    def test_the_captured_preference_carries_no_daily_cap(self) -> None:
        captured = captured_from_slot(owner=AREA, windows=(MIDDAY,))

        assert captured.max_per_day_minutes is None


class TestAWindowIsWallTimeOnTheGrid:
    def test_a_window_holds_the_two_bounds_it_was_given(self) -> None:
        assert EARLY.start == time(5, 30)
        assert EARLY.end == time(7, 0)

    def test_a_zoned_bound_is_refused(self) -> None:
        # The column stores no offset, so an offset offered here would describe a different
        # hour on every date the window is resolved against.
        with pytest.raises(PreferenceError) as refused:
            LocalTimeWindow(start=time(5, 30, tzinfo=UTC), end=time(7, 0))

        assert refused.value.field is PreferenceField.WINDOWS
        assert "zone" in str(refused.value)
        # The offending value is rendered as a time rather than as a Python repr. This message
        # reaches a caller in a 422 on the read-back path, where the request validator has not
        # already refused the offset.
        assert "05:30:00+00:00" in str(refused.value)

    @pytest.mark.parametrize(
        "bound", [time(5, 30, 30), time(5, 30, 0, 250000)], ids=["seconds", "microseconds"]
    )
    def test_a_sub_minute_bound_is_refused(self, bound: time) -> None:
        with pytest.raises(PreferenceError, match="minute-resolution"):
            LocalTimeWindow(start=bound, end=time(7, 0))

    @pytest.mark.parametrize(
        ("start", "end"),
        [(time(5, 7), time(7, 0)), (time(5, 30), time(7, 8))],
        ids=["start", "end"],
    )
    def test_a_bound_off_the_quarter_hour_is_refused(self, start: time, end: time) -> None:
        # The side this module takes on the open grid question: a user-chosen wall time owes
        # the grid, because the placement it asks for does.
        with pytest.raises(PreferenceError) as refused:
            LocalTimeWindow(start=start, end=end)

        assert refused.value.field is PreferenceField.WINDOWS
        assert "quarter hour" in str(refused.value)

    def test_every_quarter_hour_of_the_day_is_a_legal_bound(self) -> None:
        # The control. A refusal that rejected every wall time would pass both cases above.
        last = time(23, 45)
        starts = [time(hour, minute) for hour in range(24) for minute in (0, 15, 30, 45)]

        for start in starts:
            if start == last:
                continue
            assert LocalTimeWindow(start=start, end=last).start == start

    def test_a_window_that_ends_where_it_starts_is_refused(self) -> None:
        with pytest.raises(PreferenceError, match="no placement"):
            LocalTimeWindow(start=time(5, 30), end=time(5, 30))

    def test_a_window_that_ends_before_it_starts_is_refused(self) -> None:
        # A window across midnight names two stretches on two dates, and a declaration holds
        # no date to say which half belongs to which.
        with pytest.raises(PreferenceError, match="two stretches"):
            LocalTimeWindow(start=time(23, 0), end=time(1, 0))

    def test_a_window_renders_as_the_read_model_shows_it(self) -> None:
        assert str(EARLY) == "05:30-07:00"
        assert str(MIDDAY) == "13:15-14:15"


class TestTheWindowList:
    def test_no_window_at_all_is_a_preference(self) -> None:
        # An Area capping its daily minutes states nothing about the time of day, and an
        # override with no windows opts out of its Area's.
        assert a_preference(windows=()).windows == ()

    def test_windows_are_canonically_ordered_earliest_first(self) -> None:
        # So the times of day a preference names are a set: two orders of one set are one
        # preference, and a request that only reorders them changes nothing.
        assert a_preference(windows=(MIDDAY, EARLY)).windows == (EARLY, MIDDAY)
        assert a_preference(windows=(MIDDAY, EARLY)) == a_preference(windows=(EARLY, MIDDAY))

    def test_two_overlapping_windows_are_refused(self) -> None:
        with pytest.raises(PreferenceError) as refused:
            a_preference(windows=(EARLY, LocalTimeWindow(start=time(6, 0), end=time(8, 0))))

        assert refused.value.field is PreferenceField.WINDOWS
        assert "overlap" in str(refused.value)

    def test_the_overlap_rule_reads_the_canonical_order_rather_than_the_given_one(self) -> None:
        # The later window is passed FIRST here, so a rule stated over the given order would
        # find no overlap and store a pair whose union is one window.
        with pytest.raises(PreferenceError, match="overlap"):
            a_preference(windows=(LocalTimeWindow(start=time(6, 0), end=time(8, 0)), EARLY))

    def test_two_windows_that_touch_are_accepted(self) -> None:
        # Their union is one window and saying it as two is odd rather than wrong, so the rule
        # refuses genuine overlap only.
        touching = (EARLY, LocalTimeWindow(start=time(7, 0), end=time(8, 0)))

        assert a_preference(windows=touching).windows == touching

    def test_more_windows_than_the_bound_are_refused(self) -> None:
        too_many = tuple(
            LocalTimeWindow(start=time(hour, 0), end=time(hour, 30))
            for hour in range(MAX_WINDOWS + 1)
        )

        with pytest.raises(PreferenceError, match=str(MAX_WINDOWS)):
            a_preference(windows=too_many)

    def test_exactly_the_bound_is_accepted(self) -> None:
        # The control for the bound above: without it, the refusal would be indistinguishable
        # from one that rejects every list.
        at_the_bound = tuple(
            LocalTimeWindow(start=time(hour, 0), end=time(hour, 30)) for hour in range(MAX_WINDOWS)
        )

        assert len(a_preference(windows=at_the_bound).windows) == MAX_WINDOWS


class TestTheIdealDuration:
    def test_no_ideal_duration_is_a_preference(self) -> None:
        assert a_preference().preferred_duration_minutes is None

    @pytest.mark.parametrize(
        "minutes",
        [
            MIN_PREFERRED_DURATION_MINUTES - SNAP_MINUTES,
            MAX_PREFERRED_DURATION_MINUTES + SNAP_MINUTES,
        ],
        ids=["under", "over"],
    )
    def test_a_duration_outside_the_bounds_is_refused(self, minutes: int) -> None:
        with pytest.raises(PreferenceError) as refused:
            a_preference(preferred_duration_minutes=minutes)

        assert refused.value.field is PreferenceField.PREFERRED_DURATION

    def test_a_duration_off_the_grid_is_refused(self) -> None:
        # A block starts and ends on the grid, so an ideal length off it could not be met by
        # any placement and the fragmentation cost would never reach zero.
        with pytest.raises(PreferenceError, match="whole number"):
            a_preference(preferred_duration_minutes=25)

    def test_a_duration_on_the_grid_is_accepted(self) -> None:
        assert a_preference(preferred_duration_minutes=90).preferred_duration_minutes == 90

    def test_the_floor_is_one_grid_step(self) -> None:
        assert MIN_PREFERRED_DURATION_MINUTES == SNAP_MINUTES

    def test_a_duration_longer_than_the_widest_window_is_accepted(self) -> None:
        # Both are costs, so the tension between them is something the solver trades off
        # rather than a contradiction the boundary should refuse.
        narrow = LocalTimeWindow(start=time(5, 30), end=time(6, 0))

        assert a_preference(windows=(narrow,), preferred_duration_minutes=90) is not None


class TestNoRefusalPutsAPythonReprOnTheWire:
    """Every message this module raises reaches a caller in a 422, so none may carry type names.

    Stated over every refusal that interpolates a value rather than over the one that leaked, so a
    later bound added with ``{value!r}`` fails here rather than in a support ticket. A quoted STRING
    is a different case and is fine: quoting a bad string is what a reader of it needs.
    """

    @staticmethod
    def refusals() -> list[str]:
        offenders: list[Callable[[], object]] = [
            lambda: LocalTimeWindow(start=time(5, 30, tzinfo=UTC), end=time(7, 0)),
            lambda: LocalTimeWindow(start=time(5, 30, 30), end=time(7, 0)),
            lambda: LocalTimeWindow(start=time(5, 7), end=time(7, 0)),
            lambda: LocalTimeWindow(start=time(23, 0), end=time(1, 0)),
            lambda: a_preference(windows=(EARLY, LocalTimeWindow(time(6, 0), time(8, 0)))),
            lambda: a_preference(
                windows=tuple(
                    LocalTimeWindow(start=time(hour, 0), end=time(hour, 30))
                    for hour in range(MAX_WINDOWS + 1)
                )
            ),
            lambda: a_preference(preferred_duration_minutes=10),
            lambda: a_preference(preferred_duration_minutes=25),
            lambda: a_preference(HABIT, max_per_day_minutes=180),
            lambda: a_preference(AREA, max_per_day_minutes=14),
        ]
        found: list[str] = []
        for offender in offenders:
            with pytest.raises(PreferenceError) as refused:
                offender()
            found.append(str(refused.value))
        return found

    def test_every_refusal_was_collected(self) -> None:
        # The control. Every assertion below iterates the collection, so on an empty one they
        # would pass while proving nothing.
        assert len(self.refusals()) == 10

    def test_no_message_carries_a_python_type_name(self) -> None:
        leaked = [message for message in self.refusals() if "datetime" in message]

        assert leaked == []

    def test_no_message_carries_a_keyword_argument(self) -> None:
        leaked = [message for message in self.refusals() if "tzinfo" in message or "=" in message]

        assert leaked == []


class TestTheOwner:
    def test_exactly_three_kinds_of_owner_exist(self) -> None:
        assert [kind.value for kind in PreferenceOwnerKind] == ["area", "habit", "task"]

    def test_only_an_area_is_the_root_of_a_chain(self) -> None:
        assert AREA.is_an_area
        assert not HABIT.is_an_area
        assert not TASK.is_an_area

    def test_an_owner_names_one_thing(self) -> None:
        # Two fields rather than three nullable ones: a shape that could hold an Area and a
        # Habit at once would need a rule saying it must not.
        assert AREA.id != HABIT.id
        assert PreferenceOwner(kind=PreferenceOwnerKind.HABIT, id=AREA.id) != AREA
