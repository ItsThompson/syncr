"""What counts as a transition, what a verdict looks like as a row, and what an episode is.

Pure. No database and no fixtures: the rule is a function of one verdict and one stored row, the
projection is a function of one verdict, and the episode definition is a function of a week's rows.
The paths that WRITE these are driven against a real Postgres in the four suites that own them.

Four groups.

**The reading a row records is not the verdict's own field.** ``Verdict.feasible`` is refused for a
probe verdict, so it is always false, and a row copying it would report every healthy week as
broken. What the row carries is whether a gap was found.

**What counts as a transition, and the maintainer's narrower rule.** The first verdict for a week, a
change in ``feasible``, and a change in provenance while infeasible are transitions; the maintainer
records only the second of the three, and for it a week with no row at all reads as feasible.

**A row refuses itself before it reaches the corpus** when its surface and provenance disagree or
when a solver verdict names no operation. The corpus is never pruned, so the write is the only
moment a wrong field can be caught.

**The episode.** The span from a transition to infeasible until the next transition to feasible,
whose FIRST row decides whether the infeasibility was caught early. The trace from ``18`` is driven
whole, because the row-counting formula it rejects tops out at 0.5 on it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from syncr_api.plans.declarations import VerdictToRecord
from syncr_api.plans.episodes import caught_early_ratio, episodes
from syncr_api.plans.errors import VerdictNotRecordable
from syncr_api.plans.records import VerdictEventRecord
from syncr_api.plans.surfaces import REACHABLE_PAIRS, VerdictSurface
from syncr_api.plans.verdict_transitions import as_recorded, is_a_transition
from syncr_domain.feasibility import Provenance, Shortfall, ShortfallKind, Verdict
from syncr_domain.weeks import IsoWeek

WEEK = IsoWeek(2026, 7)
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)
A_TENANT = uuid4()

FLOOR_GAP = Shortfall(
    kind=ShortfallKind.FLOORS_EXCEED_CAPACITY,
    minutes=60,
    against=("every Area floor",),
    honoring=("2h of capacity left in the week",),
)
DEADLINE_GAP = Shortfall(
    kind=ShortfallKind.DEADLINE_CAPACITY,
    minutes=140,
    against=("F&F Past Papers",),
    honoring=("its Friday 09:00 deadline",),
    deadline=NOW + timedelta(days=2),
)
ANOTHER_FLOOR_GAP = Shortfall(
    kind=ShortfallKind.AREA_FLOOR_UNREACHABLE,
    minutes=45,
    against=("Career",),
    honoring=("its 3h floor",),
)


def a_verdict(
    *,
    provenance: Provenance = Provenance.PROBE,
    feasible: bool = False,
    shortfalls: tuple[Shortfall, ...] = (),
    computed_at: datetime = NOW,
    input_version: int = 1,
) -> Verdict:
    return Verdict(
        feasible=feasible,
        provenance=provenance,
        computed_at=computed_at,
        input_version=input_version,
        discretionary_minutes=6000,
        shortfalls=shortfalls,
    )


def a_row(
    *,
    provenance: Provenance = Provenance.PROBE,
    feasible: bool = False,
    surface: VerdictSurface = VerdictSurface.PIN,
    session_mode_active: bool = False,
    occurred_at: datetime = NOW,
    shortfall_minutes: int = 60,
) -> VerdictEventRecord:
    """One stored transition, as the repository hands it back."""
    return VerdictEventRecord(
        id=uuid4(),
        tenant_id=A_TENANT,
        iso_week=WEEK,
        occurred_at=occurred_at,
        provenance=provenance,
        feasible=feasible,
        shortfall_minutes=0 if feasible else shortfall_minutes,
        shortfall_kinds=() if feasible else (ShortfallKind.FLOORS_EXCEED_CAPACITY,),
        surface=surface,
        session_mode_active=session_mode_active,
        input_version=1,
        caused_by_operation_id=uuid4() if provenance is Provenance.SOLVER else None,
    )


def recorded(
    verdict: Verdict,
    *,
    surface: VerdictSurface = VerdictSurface.PIN,
    session_mode_active: bool = False,
) -> VerdictToRecord:
    return as_recorded(
        verdict,
        iso_week=WEEK,
        surface=surface,
        session_mode_active=session_mode_active,
        caused_by=uuid4() if surface is VerdictSurface.SOLVE else None,
    )


# --------------------------------------------------------------------------------
# The reading a row records
# --------------------------------------------------------------------------------


def test_a_probe_that_found_no_gap_records_the_week_as_able_to_hold_its_commitments() -> None:
    """The translation, and the field it is NOT copying.

    ``Verdict.feasible`` is false on every probe verdict, because capacity arithmetic may not claim
    a week works. A row that carried that field would open an infeasibility episode on every pin.
    """
    verdict = a_verdict()
    assert verdict.feasible is False
    assert verdict.capacity_is_sufficient

    assert recorded(verdict).feasible is True


def test_a_probe_that_found_a_gap_records_the_week_as_unable() -> None:
    assert recorded(a_verdict(shortfalls=(FLOOR_GAP,))).feasible is False


def test_a_solver_verdict_records_what_it_proved() -> None:
    """The only provenance whose own ``feasible`` field the row can take as it stands."""
    solved = a_verdict(provenance=Provenance.SOLVER, feasible=True)

    assert recorded(solved, surface=VerdictSurface.SOLVE).feasible is True


def test_the_recorded_gap_is_the_largest_one_rather_than_their_sum() -> None:
    """Shortfalls can measure the same minutes twice, so their sum is not a duration.

    A deadline gap and the floor gap of the Area that deadline belongs to are the same capacity seen
    two ways: summed, they can exceed the week. The largest single gap is a real quantity, and the
    metric job that reads it is the one place that could argue for another.
    """
    verdict = a_verdict(shortfalls=(FLOOR_GAP, DEADLINE_GAP, ANOTHER_FLOOR_GAP))

    assert recorded(verdict).shortfall_minutes == DEADLINE_GAP.minutes


def test_a_feasible_row_records_no_gap_at_all() -> None:
    assert recorded(a_verdict()).shortfall_minutes == 0


def test_the_kinds_are_deduplicated_in_the_order_the_verdict_named_them() -> None:
    """Two gaps of one kind are two gaps of the same sort, and the column answers which sorts."""
    verdict = a_verdict(shortfalls=(DEADLINE_GAP, FLOOR_GAP, DEADLINE_GAP))

    assert recorded(verdict).shortfall_kinds == (
        ShortfallKind.DEADLINE_CAPACITY,
        ShortfallKind.FLOORS_EXCEED_CAPACITY,
    )


def test_the_row_takes_its_instant_from_the_verdict_rather_than_from_a_clock() -> None:
    """One instant made structural: the assembler stamps it and the row carries it from there.

    So the maintainer cannot evaluate a tick's transitions against two instants, and there is no
    clock in the recorder to read.
    """
    computed_at = NOW + timedelta(minutes=37)

    assert recorded(a_verdict(computed_at=computed_at)).occurred_at == computed_at


def test_the_row_carries_the_version_the_verdict_was_computed_against() -> None:
    assert recorded(a_verdict(input_version=47)).input_version == 47


# --------------------------------------------------------------------------------
# what counts as a transition, and the maintainer's narrowing of it
# --------------------------------------------------------------------------------


def test_the_first_verdict_a_mutation_computes_for_a_week_is_a_transition() -> None:
    """The baseline, without which a later flip is a flip against nothing."""
    assert is_a_transition(recorded(a_verdict()), since=None) is True


def test_a_verdict_recomputed_identically_is_not_a_transition() -> None:
    """What makes a burst of twelve pins write at most one row."""
    since = a_row(feasible=True, shortfall_minutes=0)

    assert is_a_transition(recorded(a_verdict()), since=since) is False


@pytest.mark.parametrize("was_feasible", [True, False])
def test_a_change_in_feasible_is_always_a_transition(was_feasible: bool) -> None:
    verdict = a_verdict(shortfalls=() if not was_feasible else (FLOOR_GAP,))
    since = a_row(feasible=was_feasible)

    assert is_a_transition(recorded(verdict), since=since) is True


def test_a_provenance_change_while_infeasible_is_a_transition() -> None:
    """The second row of a pair: the arithmetic's warning, confirmed by an attempted placement."""
    confirmed = a_verdict(provenance=Provenance.SOLVER, shortfalls=(FLOOR_GAP,))
    since = a_row(provenance=Provenance.PROBE, feasible=False)

    assert is_a_transition(recorded(confirmed, surface=VerdictSurface.SOLVE), since=since) is True


def test_a_provenance_change_while_feasible_is_not_a_transition() -> None:
    """There is nothing to confirm about a week nobody has said is impossible."""
    solved = a_verdict(provenance=Provenance.SOLVER, feasible=True)
    since = a_row(feasible=True, shortfall_minutes=0)

    assert is_a_transition(recorded(solved, surface=VerdictSurface.SOLVE), since=since) is False


def test_the_maintainer_records_no_provenance_change_at_all() -> None:
    """The maintainer's probe re-derives provenance, so this would flip-flop after every solve."""
    probed = a_verdict(shortfalls=(FLOOR_GAP,))
    since = a_row(provenance=Provenance.SOLVER, feasible=False)

    row = recorded(probed, surface=VerdictSurface.MAINTAINER)

    assert is_a_transition(row, since=since) is False


def test_the_maintainer_records_a_flip_in_either_direction() -> None:
    to_infeasible = recorded(a_verdict(shortfalls=(FLOOR_GAP,)), surface=VerdictSurface.MAINTAINER)
    to_feasible = recorded(a_verdict(), surface=VerdictSurface.MAINTAINER)

    assert is_a_transition(to_infeasible, since=a_row(feasible=True, shortfall_minutes=0)) is True
    assert is_a_transition(to_feasible, since=a_row(feasible=False)) is True


def test_the_maintainer_says_nothing_about_a_week_it_finds_healthy_and_has_no_row_for() -> None:
    """A week with no row holds no open episode, which is the state a feasible row denotes.

    So a periodic probe reporting that a week is fine is not a discovery, which is the same argument
    applied to the absent baseline. A mutation records it because a person touched the week.
    """
    healthy = a_verdict()

    assert (
        is_a_transition(recorded(healthy, surface=VerdictSurface.MAINTAINER), since=None) is False
    )
    assert is_a_transition(recorded(healthy, surface=VerdictSurface.PIN), since=None) is True


def test_the_maintainer_records_a_first_verdict_that_is_a_discovery() -> None:
    """A week that is impossible the first time the maintainer ever probes it IS a discovery."""
    found = recorded(a_verdict(shortfalls=(FLOOR_GAP,)), surface=VerdictSurface.MAINTAINER)

    assert is_a_transition(found, since=None) is True


# --------------------------------------------------------------------------------
# A row refuses itself before it reaches the corpus
# --------------------------------------------------------------------------------


def test_a_surface_and_a_provenance_that_disagree_are_refused() -> None:
    """A miswiring rather than anything a request carried, and the corpus is never pruned."""
    with pytest.raises(VerdictNotRecordable, match="pin"):
        VerdictToRecord(
            iso_week=WEEK,
            occurred_at=NOW,
            provenance=Provenance.SOLVER,
            feasible=False,
            shortfall_minutes=60,
            shortfall_kinds=(ShortfallKind.FLOORS_EXCEED_CAPACITY,),
            surface=VerdictSurface.PIN,
            session_mode_active=False,
            input_version=1,
            caused_by_operation_id=uuid4(),
        )


def test_a_solver_verdict_that_names_no_operation_is_refused() -> None:
    with pytest.raises(VerdictNotRecordable, match="solver"):
        VerdictToRecord(
            iso_week=WEEK,
            occurred_at=NOW,
            provenance=Provenance.SOLVER,
            feasible=True,
            shortfall_minutes=0,
            shortfall_kinds=(),
            surface=VerdictSurface.SOLVE,
            session_mode_active=False,
            input_version=1,
        )


def test_a_probe_verdict_that_names_an_operation_is_refused() -> None:
    """Arithmetic on a request is caused by nothing a reader could follow."""
    with pytest.raises(VerdictNotRecordable, match="probe"):
        VerdictToRecord(
            iso_week=WEEK,
            occurred_at=NOW,
            provenance=Provenance.PROBE,
            feasible=False,
            shortfall_minutes=60,
            shortfall_kinds=(ShortfallKind.FLOORS_EXCEED_CAPACITY,),
            surface=VerdictSurface.PIN,
            session_mode_active=False,
            input_version=1,
            caused_by_operation_id=uuid4(),
        )


def test_every_surface_reaches_a_verdict_exactly_one_way() -> None:
    """The datum the refusal above and the metric's label set are both stated over."""
    assert dict(REACHABLE_PAIRS) == {
        VerdictSurface.PIN: Provenance.PROBE,
        VerdictSurface.MUTATION: Provenance.PROBE,
        VerdictSurface.TRADEOFF: Provenance.PROBE,
        VerdictSurface.SOLVE: Provenance.SOLVER,
        VerdictSurface.CLI: Provenance.PROBE,
        VerdictSurface.MAINTAINER: Provenance.PROBE,
    }


def test_the_six_members_are_the_only_ones_this_package_writes() -> None:
    """Two were dropped: ``weekly_session`` was a read and ``horizon`` folds into the maintainer.

    The enum half only. That the COLUMN refuses a seventh word is driven in
    ``test_plan_schema_integration.py::test_a_feasible_verdict_cannot_carry_a_shortfall``, which
    inserts ``surface="week_screen"`` and reads the constraint's refusal back.
    """
    assert [surface.value for surface in VerdictSurface] == [
        "pin",
        "mutation",
        "tradeoff",
        "solve",
        "cli",
        "maintainer",
    ]


# --------------------------------------------------------------------------------
# the episode
# --------------------------------------------------------------------------------


def at(minutes: int) -> datetime:
    return NOW + timedelta(minutes=minutes)


def test_an_episode_runs_from_a_transition_to_infeasible_until_the_next_to_feasible() -> None:
    rows = [
        a_row(feasible=False, occurred_at=at(0)),
        a_row(feasible=True, occurred_at=at(30)),
    ]

    (episode,) = episodes(rows)

    assert episode.began_at == at(0)
    assert episode.ended_at == at(30)
    assert episode.is_open is False


def test_the_first_row_of_an_episode_decides_whether_it_was_caught_early() -> None:
    """The episode's first row decides it, and the trace from ``18``: a pin, then a worker.

    The confirming row carries ``session_mode_active = false`` because the worker cannot know, so
    reading any row but the first would report a catch as a miss. The row-counting figure is
    asserted beside the episode figure, because it is the one a later reader would reach for first.
    """
    rows = [
        a_row(
            surface=VerdictSurface.PIN, feasible=False, session_mode_active=True, occurred_at=at(0)
        ),
        a_row(
            surface=VerdictSurface.SOLVE,
            provenance=Provenance.SOLVER,
            feasible=False,
            occurred_at=at(2),
        ),
    ]

    (episode,) = episodes(rows)

    assert episode.caught_early is True
    assert episode.confirmations == (rows[1],)
    assert caught_early_ratio([episode]) == 1.0
    assert sum(one.session_mode_active for one in rows) / len(rows) == 0.5


def test_a_week_that_broke_twice_holds_two_episodes() -> None:
    """Infeasible, resolved, infeasible again is two discoveries and counts as two."""
    rows = [
        a_row(feasible=False, session_mode_active=True, occurred_at=at(0)),
        a_row(feasible=True, occurred_at=at(30)),
        a_row(surface=VerdictSurface.MAINTAINER, feasible=False, occurred_at=at(60)),
    ]

    first, second = episodes(rows)

    assert first.caught_early is True
    assert second.caught_early is False, "no session was open and no user action caused it"
    assert second.is_open
    assert caught_early_ratio([first, second]) == 0.5


def test_an_episode_that_never_closes_still_counts_once() -> None:
    rows = [a_row(feasible=False, occurred_at=at(0)), a_row(feasible=False, occurred_at=at(15))]

    (episode,) = episodes(rows)

    assert episode.is_open
    assert episode.ended_at is None
    assert episode.confirmations == (rows[1],)


def test_a_feasible_row_with_no_open_episode_opens_nothing() -> None:
    """The first verdict a mutation records for a healthy week is exactly that row."""
    assert episodes([a_row(feasible=True, occurred_at=at(0))]) == ()


def test_a_week_with_no_rows_holds_no_episodes() -> None:
    assert episodes([]) == ()


def test_a_period_with_no_episode_has_no_ratio_rather_than_a_ratio_of_zero() -> None:
    """A period with no infeasibility is not a period in which none was caught."""
    assert caught_early_ratio([]) is None
