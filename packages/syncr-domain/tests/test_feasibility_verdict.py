"""The verdict vocabulary: the claim it may not make, and the shortfall it may not render.

Three of these are stated over the vocabulary itself rather than over a behaviour, which is
deliberate. ``ShortfallKind`` crosses the API boundary, renders on three surfaces, and is
aggregated by a metric job, so a fifth spelling of it anywhere is a second vocabulary; and the
reachability test is what stops a member being carried for years with nothing able to produce it.
"""

from __future__ import annotations

import pytest

from syncr_domain.feasibility import (
    FeasibilityError,
    Provenance,
    Shortfall,
    ShortfallKind,
    Verdict,
    hours_and_minutes,
    minimum_chunk_shortfall,
    probe,
)
from tests.instants import at
from tests.probe_weeks import CAREER, FITNESS, NOW, WEEK, a_demand, a_reservation, a_week


def a_shortfall(**overrides: object) -> Shortfall:
    stated: dict[str, object] = {
        "kind": ShortfallKind.DEADLINE_CAPACITY,
        "minutes": 80,
        "against": ("F&F Past Papers",),
        "honoring": ("the Fitness floor of 5h",),
    }
    stated.update(overrides)
    return Shortfall(**stated)  # type: ignore[arg-type]


def a_verdict(**overrides: object) -> Verdict:
    stated: dict[str, object] = {
        "feasible": False,
        "provenance": Provenance.PROBE,
        "computed_at": NOW,
        "input_version": 12,
        "discretionary_minutes": 6000,
    }
    stated.update(overrides)
    return Verdict(**stated)  # type: ignore[arg-type]


def test_the_four_kinds_are_the_whole_vocabulary() -> None:
    # An equality rather than a containment: a fifth member has to be added here, which is where
    # the question "which producer emits it, and which surface renders it" gets asked.
    assert {kind.value for kind in ShortfallKind} == {
        "floors_exceed_capacity",
        "deadline_capacity",
        "area_floor_unreachable",
        "minimum_chunk_unplaceable",
    }


def test_every_kind_has_a_producer_that_really_emits_it() -> None:
    # A member no code can produce makes its own test pass vacuously forever, so the producers are
    # enumerated and run: the probe for the three capacity kinds, and the named constructor for
    # the packing failure the probe structurally cannot find.
    #
    # Sunday 23:00 with both floors still unmet is the state that reaches all three at once: one
    # hour of capacity left, ten hours of floor to find, and ten hours of work due by the end of
    # the week.
    sunday_night = a_week(
        now=at(23, day=6),
        area_floor_reservations=(a_reservation(FITNESS, 300), a_reservation(CAREER, 300)),
        deadline_demands=(a_demand(CAREER, 600, WEEK.end),),
    )

    produced = {shortfall.kind for shortfall in probe(sunday_night).shortfalls}
    produced.add(
        minimum_chunk_shortfall(minutes=180, chunk_minutes=50, against=("F&F Past Papers",)).kind
    )

    assert produced == set(ShortfallKind)


def test_a_packing_failure_names_the_chunk_no_window_could_hold() -> None:
    # The one thing the solver knows and the probe cannot: three hours of free time in six
    # half-hour gaps is three hours to every total the probe takes and no minutes at all to a
    # task that may not be split below fifty.
    shortfall = minimum_chunk_shortfall(
        minutes=180,
        chunk_minutes=50,
        against=("F&F Past Papers",),
        blocked_by=("H4: no window of 50m before Fri 09:00",),
        deadline=at(9, day=4),
        area_id=CAREER,
    )

    assert shortfall.kind is ShortfallKind.MINIMUM_CHUNK_UNPLACEABLE
    assert shortfall.honoring == (
        "its 50m minimum chunk",
        "H4: no window of 50m before Fri 09:00",
    )


def test_no_verdict_from_capacity_arithmetic_may_claim_a_week_works() -> None:
    # The one claim the product must never make, refused where it would be constructed rather
    # than left to each of the five surfaces that read the field.
    with pytest.raises(FeasibilityError):
        a_verdict(feasible=True)


def test_a_solver_verdict_may_claim_either() -> None:
    # The asymmetry is the point of provenance: an attempted placement knows the answer.
    assert a_verdict(feasible=True, provenance=Provenance.SOLVER).feasible
    assert not a_verdict(feasible=False, provenance=Provenance.SOLVER).feasible


def test_capacity_being_sufficient_is_not_a_claim_that_the_week_works() -> None:
    # A probe verdict finding nothing reports that capacity is sufficient. `feasible` stays
    # false, so a surface that renders it cannot say "this week works" by accident.
    verdict = probe(a_week())

    assert verdict.capacity_is_sufficient
    assert not verdict.feasible
    assert verdict.provenance is Provenance.PROBE


def test_a_verdict_holding_a_gap_does_not_report_capacity_as_sufficient() -> None:
    assert not a_verdict(shortfalls=(a_shortfall(),)).capacity_is_sufficient


@pytest.mark.parametrize("named", [(), ("",), ("Fitness", "   ")])
def test_a_shortfall_that_names_nothing_it_cannot_satisfy_is_refused(
    named: tuple[str, ...],
) -> None:
    with pytest.raises(FeasibilityError):
        a_shortfall(against=named)


@pytest.mark.parametrize("named", [(), ("",), ("the Fitness floor of 5h", " ")])
def test_a_shortfall_honoring_no_constraint_is_refused(named: tuple[str, ...]) -> None:
    # `honoring` is what makes a refusal actionable rather than merely negative: it names which
    # of the user's own constraints produced the gap, which is what they choose a tradeoff
    # against. A gap that names none is a gap they cannot act on.
    with pytest.raises(FeasibilityError):
        a_shortfall(honoring=named)


@pytest.mark.parametrize("minutes", [0, -60])
def test_a_gap_of_no_minutes_is_not_a_shortfall(minutes: int) -> None:
    # A check that found enough capacity reports nothing at all rather than a gap of none, so a
    # surface counting shortfalls counts problems.
    with pytest.raises(FeasibilityError):
        a_shortfall(minutes=minutes)


def test_a_week_holding_a_negative_denominator_is_refused() -> None:
    with pytest.raises(FeasibilityError):
        a_verdict(discretionary_minutes=-1)


@pytest.mark.parametrize(
    ("minutes", "rendered"),
    [(0, "0m"), (45, "45m"), (60, "1h"), (80, "1h20m"), (300, "5h"), (1440, "24h")],
)
def test_a_duration_renders_as_the_panel_and_the_cli_print_it(minutes: int, rendered: str) -> None:
    assert hours_and_minutes(minutes) == rendered


def test_a_negative_duration_renders_as_nothing_and_is_refused() -> None:
    with pytest.raises(FeasibilityError):
        hours_and_minutes(-1)
