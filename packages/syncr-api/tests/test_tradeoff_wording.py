"""The wording a tradeoff is offered in, and the distribution its nights come from.

Two small modules, tested directly rather than only through an assembly, because both answer
questions an assembly cannot ask cleanly: how a list of three nights reads, and what a gap does
when the nights cannot supply it. The enumeration suite exercises both over real weeks; this is
where their edges live.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from syncr_api.plans import tradeoff_labels as labels
from syncr_api.plans import tradeoff_nights as nights
from syncr_domain.fixtures import elastic_sleep
from syncr_domain.identity import date_occurrence_key
from syncr_domain.intervals import Interval
from syncr_solver.inputs import FrameEntry

WEEK_DATES = list(elastic_sleep.WEEK.dates())
DATES = {date_occurrence_key(on): on for on in WEEK_DATES}


def a_night(
    *,
    day: int,
    duration_minutes: int = elastic_sleep.DURATION_MINUTES,
    min_duration_minutes: int = elastic_sleep.MIN_DURATION_MINUTES,
    routine_id: object = None,
    title: str = elastic_sleep.TITLE,
) -> FrameEntry:
    """One routine occurrence, at 23:00 on the ``day``-th date of the fixture's week."""
    start = datetime.combine(WEEK_DATES[day], elastic_sleep.TARGET_TIME, tzinfo=UTC)
    return FrameEntry(
        routine_id=routine_id or uuid4(),  # type: ignore[arg-type]
        occurrence_key=date_occurrence_key(WEEK_DATES[day]),
        interval=Interval(start, start + timedelta(minutes=duration_minutes)),
        min_duration_minutes=min_duration_minutes,
        flex_band_minutes=30,
        title=title,
    )


# --------------------------------------------------------------------------------
# The words
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        ((1,), "Tue"),
        ((1, 2), "Tue and Wed"),
        ((1, 2, 3), "Tue, Wed and Thu"),
        ((0, 5, 6), "Mon, Sat and Sun"),
    ],
)
def test_the_nights_read_as_a_list_with_no_serial_comma(
    days: tuple[int, ...], expected: str
) -> None:
    assert labels.nights_named([WEEK_DATES[day] for day in days]) == expected


def test_the_weekday_names_are_the_products_own_rather_than_the_process_locale() -> None:
    # `strftime("%a")` reads the locale, so a label would change with an environment variable. The
    # names are indexed by `date.weekday()`, Monday first.
    assert labels.WEEKDAY_NAMES == ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    assert [labels.WEEKDAY_NAMES[on.weekday()] for on in WEEK_DATES[:3]] == ["Mon", "Tue", "Wed"]


def test_each_label_names_its_target_in_the_users_own_words() -> None:
    # The title and the Area name are what the user typed. The spec's example label lowercases a
    # routine a user capitalized, and following the example rather than the declaration would put a
    # word on the panel the user never wrote.
    assert labels.dropped(title="Kim's Game Project") == "Drop Kim's Game Project this week"
    assert (
        labels.partial_accepted(title="F&F Past Papers")
        == "Accept partial delivery on F&F Past Papers"
    )
    assert labels.floor_breached(name="Fitness", minutes=80) == "Breach the Fitness floor by 1h20m"
    assert (
        labels.routine_reduced(title="Sleep", minutes_each=20, nights=WEEK_DATES[1:4])
        == elastic_sleep.LABEL
    )


# --------------------------------------------------------------------------------
# The distribution
# --------------------------------------------------------------------------------


def test_a_gap_takes_the_fewest_nights_that_can_supply_it() -> None:
    # Sixty minutes against twenty a night is three nights, which is the PRD's own phrasing and a
    # consequence of the give rather than a number chosen here.
    distribution = nights.distributed(
        elastic_sleep.GAP_MINUTES, over=[a_night(day=day) for day in (1, 2, 3, 4)], dates=DATES
    )

    assert distribution is not None
    assert distribution.each == elastic_sleep.GIVE_MINUTES
    assert distribution.reductions == elastic_sleep.REDUCTIONS
    assert distribution.recovers == elastic_sleep.GAP_MINUTES


def test_a_night_the_concession_does_not_need_is_left_whole() -> None:
    # A gap of twenty minutes takes one night of the four, because the others are not needed.
    distribution = nights.distributed(
        20, over=[a_night(day=day) for day in (1, 2, 3, 4)], dates=DATES
    )

    assert distribution is not None
    assert list(distribution.reductions) == [elastic_sleep.TUESDAY]


def test_a_routine_with_no_give_is_no_distribution_at_all() -> None:
    # The default state of every routine: the minimum equals the target, so there is nothing to
    # concede and no offer to make.
    rigid = a_night(day=1, min_duration_minutes=elastic_sleep.DURATION_MINUTES)

    assert nights.distributed(60, over=[rigid], dates=DATES) is None


def test_no_nights_is_no_distribution_either() -> None:
    # Every night behind `now`, or every one after the deadline: nothing eligible, nothing
    # offered.
    assert nights.distributed(60, over=[], dates=DATES) is None


def test_the_figure_per_night_is_the_smallest_give_among_the_nights_used() -> None:
    # Among the nights USED, not among every candidate. A night that can supply the whole gap on its
    # own is one night, and a second night with less give is left whole rather than dragging the
    # shared figure down to what IT could have given.
    generous = a_night(day=1, min_duration_minutes=elastic_sleep.DURATION_MINUTES - 60)
    mean = a_night(day=2, min_duration_minutes=elastic_sleep.DURATION_MINUTES - 10)

    distribution = nights.distributed(60, over=[generous, mean], dates=DATES)

    assert distribution is not None
    assert distribution.each == 60
    assert distribution.recovers == 60
    assert list(distribution.reductions) == [elastic_sleep.TUESDAY]


def test_a_trailing_low_give_night_no_longer_shrinks_the_figure_before_it() -> None:
    # Twenty, twenty and five against a forty-minute gap: two nights at twenty close it, and the
    # third is never reached. Bounding by the smallest give across ALL THREE candidates gave five
    # apiece over three nights, recovering fifteen where forty was available and taking a night the
    # concession did not need.
    #
    # TRAILING is the whole claim: the search is over prefixes, so a low-give night EARLY in the
    # week still bounds every count that reaches past it. That residual is measured below.
    gives = (20, 20, 5)
    over = [
        a_night(day=index + 1, min_duration_minutes=elastic_sleep.DURATION_MINUTES - give)
        for index, give in enumerate(gives)
    ]

    distribution = nights.distributed(40, over=over, dates=DATES)

    assert distribution is not None
    assert distribution.each == 20
    assert distribution.recovers == 40
    assert list(distribution.reductions) == [elastic_sleep.TUESDAY, elastic_sleep.WEDNESDAY]


@pytest.mark.parametrize(
    ("gives", "each", "recovers"),
    [
        ((5, 20, 20), 5, 15),
        ((20, 5, 20), 20, 20),
    ],
)
def test_a_low_give_night_early_in_the_week_still_bounds_the_nights_after_it(
    gives: tuple[int, ...], each: int, recovers: int
) -> None:
    # The residual of searching prefixes, measured rather than described. Forty minutes were
    # available over the two twenty-minute nights in each case, and the concession offers less
    # because every prefix that reaches them also contains the low one.
    #
    # Recorded rather than fixed: searching subsets would recover more and would stop naming a
    # prefix, which is a decision about which nights a concession may SKIP rather than an arithmetic
    # correction. Latent today because every occurrence of one routine shares its minimum, so every
    # eligible night has the same give.
    over = [
        a_night(day=index + 1, min_duration_minutes=elastic_sleep.DURATION_MINUTES - give)
        for index, give in enumerate(gives)
    ]

    distribution = nights.distributed(40, over=over, dates=DATES)

    assert distribution is not None
    assert distribution.each == each
    assert distribution.recovers == recovers


def test_a_night_with_no_give_is_dropped_rather_than_killing_the_offer() -> None:
    # One rigid occurrence among elastic ones must not suppress the whole routine's offer: it can
    # concede nothing, so it is not a night the distribution counts.
    elastic = a_night(day=1)
    rigid = a_night(day=2, min_duration_minutes=elastic_sleep.DURATION_MINUTES)
    later = a_night(day=3)

    distribution = nights.distributed(40, over=[elastic, rigid, later], dates=DATES)

    assert distribution is not None
    assert distribution.recovers == 2 * elastic_sleep.GIVE_MINUTES
    assert list(distribution.reductions) == [elastic_sleep.TUESDAY, elastic_sleep.THURSDAY]


def test_nights_that_cannot_reach_the_gap_are_all_used_at_their_full_give() -> None:
    # Two nights of twenty against a gap of two hours: the offer recovers forty minutes and says so,
    # which is honest rather than no offer at all.
    distribution = nights.distributed(120, over=[a_night(day=1), a_night(day=2)], dates=DATES)

    assert distribution is not None
    assert distribution.each == elastic_sleep.GIVE_MINUTES
    assert distribution.recovers == 2 * elastic_sleep.GIVE_MINUTES


def test_a_gap_that_does_not_divide_evenly_rounds_up_rather_than_falling_short() -> None:
    # Fifty minutes over twenty a night is three nights of seventeen, which recovers fifty-one. The
    # rounding is upward so the concession covers the gap rather than leaving one minute of it.
    distribution = nights.distributed(50, over=[a_night(day=day) for day in (1, 2, 3)], dates=DATES)

    assert distribution is not None
    assert distribution.each == 17
    assert distribution.recovers == 51


def test_an_occurrence_already_under_way_is_not_reducible() -> None:
    # A reduction moves the END, so part of what an occurrence under way would hand back is behind
    # `now`, where capacity has not started.
    under_way = a_night(day=0)
    ahead = a_night(day=1)
    midnight_between = under_way.interval.start + timedelta(hours=1)

    assert nights.reducible([under_way, ahead], after=midnight_between, before=None) == (ahead,)


def test_a_night_ending_after_the_deadline_cannot_answer_a_gap_measured_before_it() -> None:
    tuesday = a_night(day=1)
    wednesday = a_night(day=2)

    eligible = nights.reducible(
        [tuesday, wednesday], after=elastic_sleep.NOW, before=tuesday.interval.end
    )

    assert eligible == (tuesday,)


def test_the_occurrences_of_one_routine_are_grouped_under_it() -> None:
    sleep = uuid4()
    walk = uuid4()
    frame = [
        a_night(day=1, routine_id=sleep),
        a_night(day=1, routine_id=walk, title="Walk"),
        a_night(day=2, routine_id=sleep),
    ]

    grouped = nights.by_routine(frame)

    assert list(grouped) == [sleep, walk]
    assert [entry.occurrence_key for entry in grouped[sleep]] == [
        date_occurrence_key(elastic_sleep.TUESDAY),
        date_occurrence_key(elastic_sleep.WEDNESDAY),
    ]
