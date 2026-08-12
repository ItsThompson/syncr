"""The ``elastic_sleep`` fixture, checked against the zone rules and the arithmetic that read it.

The fixture holds literals so that a consumer asserting a distribution, a reduced span, or a
rendered label against it is making a real claim. That only works if the literals are right, so
this suite is what earns them: every instant is re-derived from ``to_instant``, every date from
the week itself, and every figure from the stated declaration.

Three of its claims are the reason it exists, and each is asserted rather than described. The give
is twenty minutes a night, so an hour cannot come off one night. Monday night has already begun at
``now``, so the earliest three nights a concession may touch are Tuesday, Wednesday and Thursday.
And the distribution sums to exactly the gap the week holds.
"""

from __future__ import annotations

from datetime import timedelta

from syncr_domain.fixtures import elastic_sleep as fixture
from syncr_domain.intervals import Interval
from syncr_domain.zones import to_instant


def night_of(day_index: int) -> Interval:
    """The occurrence the routine's declaration produces on the ``day_index``-th date of the week.

    Derived from the wall time and the zone rather than copied, which is what makes the literals in
    the fixture a claim about the declaration instead of a restatement of themselves.
    """
    on = fixture.WEEK.dates()[day_index]
    start = to_instant(fixture.TARGET_TIME, on, fixture.ZONE)
    return Interval(start, start + timedelta(minutes=fixture.DURATION_MINUTES))


def test_the_week_holds_the_three_nights_the_fixture_names() -> None:
    assert list(fixture.WEEK.dates())[1:4] == [fixture.TUESDAY, fixture.WEDNESDAY, fixture.THURSDAY]


def test_every_stated_night_is_the_span_the_declaration_produces_in_its_zone() -> None:
    assert night_of(0) == fixture.MONDAY_NIGHT
    assert night_of(1) == fixture.TUESDAY_NIGHT


def test_the_give_is_what_the_minimum_leaves_of_the_target() -> None:
    # Twenty minutes a night is the whole point: an hour cannot come off one night, so the fewest
    # nights that can supply the gap is three rather than one.
    assert fixture.GIVE_MINUTES == 20
    assert fixture.MIN_DURATION_MINUTES + fixture.GIVE_MINUTES == fixture.DURATION_MINUTES
    assert fixture.MIN_DURATION_MINUTES < fixture.DURATION_MINUTES


def test_the_distribution_covers_the_gap_and_asks_no_night_for_more_than_its_give() -> None:
    assert sum(fixture.REDUCTIONS.values()) == fixture.GAP_MINUTES
    assert set(fixture.REDUCTIONS.values()) == {fixture.GIVE_MINUTES}
    assert len(fixture.REDUCTIONS) == 3


def test_every_night_the_distribution_names_falls_inside_the_week() -> None:
    # WA7's first half, over the fixture rather than over a stored row: a reduction naming a date
    # another week owns would pair with no occurrence here.
    assert set(fixture.REDUCTIONS) <= set(fixture.WEEK.dates())


def test_mondays_night_is_wholly_behind_now_and_tuesdays_has_not_begun() -> None:
    # Which is what makes the three earliest reducible nights Tuesday, Wednesday and Thursday, and
    # the label read `on Tue, Wed and Thu`. An occurrence straddling `now` is a different case and
    # belongs to the suite that drives the enumeration, not to a week's fixture.
    assert fixture.MONDAY_NIGHT.end <= fixture.NOW
    assert fixture.TUESDAY_NIGHT.start > fixture.NOW


def test_the_reduced_night_is_the_declaration_less_one_nights_reduction() -> None:
    assert fixture.TUESDAY_NIGHT_REDUCED.start == fixture.TUESDAY_NIGHT.start
    assert (
        fixture.TUESDAY_NIGHT_REDUCED.total_minutes()
        == fixture.DURATION_MINUTES - fixture.REDUCTION_EACH
    )
    # Above the minimum, so this reduction is honoured in full rather than clamped to it.
    assert fixture.TUESDAY_NIGHT_REDUCED.total_minutes() >= fixture.MIN_DURATION_MINUTES


def test_the_label_names_each_night_and_the_figure_one_night_gives_up() -> None:
    # The crossing point between two packages: the enumerator renders this string and this fixture
    # is where the expectation lives, so a change to either side is a failure rather than a drift.
    assert fixture.LABEL == "Reduce Sleep by 20m on Tue, Wed and Thu"
    assert fixture.TITLE in fixture.LABEL
