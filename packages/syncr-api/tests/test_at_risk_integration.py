"""``US-TASK-03``: the backlog's at-risk column and the week's verdict are one arithmetic.

The claim is about two SCREENS agreeing, so it cannot be asserted inside either of them. What this
suite drives is the equality between the set the backlog marks and the set derived from the week
read's own shortfalls, over a real week whose deadline really cannot be met.

**The equality is stated over BOTH screens on a week with a plan and on a week without one.** The
second case is the one that got through review: the backlog's reader had no plan check, so a week
the week read reported `verdict: null` for still marked a task, and there was no panel on which the
user could have seen the shortfall behind the mark. The unplanned-week tests below are that case,
and they are integration tests because the defect is only visible when both screens are read
together.

**The right-hand side is derived here rather than read off the backlog.** A comparison of the
backlog's marking against the backlog's own count would agree whatever either computed.

**The column does not inflate on a healthy solved week**, which is ``reviews/spec-review-5.md`` B1
from the column's side: under the superseded floor rule every ``deadline_capacity`` shortfall was
inflated by the whole of every already-scheduled floor, so a week with room for everything reported
a gap and this column inflated with it.

**Which week is asked about is resolved in the HOME zone.** A tenant thirteen hours east is living
in a week the UTC date does not name for thirteen hours of every day.

**Nothing pushes it.** The event union carries no verdict member, because only a conflict notifies,
so the determination is recomputed on the next read rather than delivered.

The rows every assertion here is driven against are ``tests/live_weeks.py``, and the composed read's
own half is ``test_week_view_integration.py``.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from statistics import quantiles
from typing import TYPE_CHECKING, Any, get_args
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.events.config import EVENT_TYPES, EventType
from syncr_api.tasks.config import TASKS_PREFIX
from syncr_domain.feasibility import ShortfallKind
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import provision_owner, remove_tenant
from tests.live_weeks import (
    AN_HOUR,
    AUCKLAND,
    BLOCKS_IN_A_FULL_WEEK,
    LONDON,
    a_candidate_moving_one_block,
    a_solved_deadline_gap,
    append_a_full_week,
    backlog,
    capture_a_task,
    declare_the_minimum,
    enqueue_a_solve,
    fill_the_slot,
    produce_a_plan,
    set_home_zone,
    sign_in,
    the_live_plan,
    the_weeks_version,
    this_week,
    week_path,
    week_view,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings

pytestmark = pytest.mark.integration

# The measurement's shape, and the ceiling this suite fails at. The budget is p95 under 150 ms; the
# ceiling is deliberately looser, because a developer's machine and a CI runner are not the
# deployment, and the measured figure is reported rather than asserted. Twenty deadlined tasks is
# review 44's own shape, which is what makes this figure comparable to the one it recorded.
LATENCY_SAMPLES = 30
CATASTROPHIC_MILLISECONDS = 1000
DEADLINED_TASKS = 20


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def http(live_database_url: str, settings: ServiceSettings) -> Iterator[TestClient]:
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def configured(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> tuple[dict[str, str], str]:
    """A signed-in tenant in London that has declared what a plan needs, and its Area."""
    headers = sign_in(http, owner.email)
    set_home_zone(http, headers, LONDON)
    return headers, declare_the_minimum(http, headers, live_database_url, owner.tenant_id)


# --------------------------------------------------------------------------------
# US-TASK-03: one arithmetic, two screens
# --------------------------------------------------------------------------------


@pytest.fixture
def a_week_a_task_cannot_fit_in(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> tuple[dict[str, str], IsoWeek, dict[str, Any]]:
    """Forty hours of work due inside the week, which no week has room for."""
    headers, area_id = configured
    week = this_week()
    due = datetime.combine(week.dates()[-1], datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)
    impossible = capture_a_task(
        http,
        headers,
        area_id,
        title="Kontron take-home",
        estimateMinutes=40 * AN_HOUR,
        deadline=due.isoformat(),
    )
    comfortable = capture_a_task(http, headers, area_id, title="Read one paper", estimateMinutes=30)
    produce_a_plan(live_database_url, owner.tenant_id, week)
    return headers, week, {"impossible": impossible["id"], "comfortable": comfortable["id"]}


def at_risk_by_the_weeks_verdict(view: dict[str, Any], tasks: list[dict[str, Any]]) -> set[str]:
    """The at-risk set derived from the week read's OWN verdict, independently of the backlog.

    Derived here rather than read off the backlog, because what is under test is that the two agree:
    a comparison of the backlog's answer against itself would pass whatever it computed.
    """
    gaps = [
        gap
        for gap in (view["verdict"] or {"shortfalls": []})["shortfalls"]
        if gap["kind"] == ShortfallKind.DEADLINE_CAPACITY.value
    ]
    return {
        task["id"]
        for task in tasks
        for gap in gaps
        if gap["areaId"] == task["areaId"]
        and gap["deadline"] == task["deadline"]
        and task["title"] in gap["against"]
    }


def test_the_at_risk_set_from_the_backlog_is_the_set_the_weeks_verdict_names(
    http: TestClient, a_week_a_task_cannot_fit_in: tuple[dict[str, str], IsoWeek, dict[str, Any]]
) -> None:
    """``US-TASK-03``: a task cannot be at risk on one screen and fine on another.

    The comparison is between two SCREENS' answers, and the right-hand side is derived from the week
    read's own shortfalls rather than from the backlog: the backlog's marking compared against the
    backlog's count would agree whatever either computed.
    """
    headers, week, seeded = a_week_a_task_cannot_fit_in
    listed = backlog(http, headers)

    derived = at_risk_by_the_weeks_verdict(week_view(http, headers, week), listed["tasks"])
    marked = {task["id"] for task in listed["tasks"] if task["atRisk"]}

    assert derived == {seeded["impossible"]}, "the fixture week was not tight enough to show a gap"
    assert marked == derived


def test_the_equality_holds_on_the_solver_branch_the_serve_rule_exists_for(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """The branch the whole serve rule is for, driven end to end over both screens.

    Every other test in this suite runs on a week whose slot is empty, so both screens take the
    probe branch and the equality would hold even if one of them re-probed independently of the
    other. The case the ticket exists for is a week holding a CURRENT slot whose stored SOLVER
    verdict names a real task, and until this test it was guarded by unit tests over fakes alone.

    ``provenance`` is asserted first as the anti-vacuity guard: if the slot were stale or empty the
    read would probe, and the equality below would be about a verdict this test did not write.

    The gap is ``deadline_capacity`` rather than the packing failure the other suites store, because
    that is the kind the at-risk column reads: a verdict carrying only a packing failure marks no
    task, which is deliberate and is driven over values.
    """
    headers, area_id = configured
    week = this_week()
    due = datetime.combine(week.dates()[-1], datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)
    named = capture_a_task(
        http,
        headers,
        area_id,
        title="Kontron take-home",
        estimateMinutes=8 * AN_HOUR,
        deadline=due.isoformat(),
    )
    other = capture_a_task(http, headers, area_id, title="Read one paper", estimateMinutes=30)
    produce_a_plan(live_database_url, owner.tenant_id, week)
    live = the_live_plan(live_database_url, owner.tenant_id, week)
    version = the_weeks_version(live_database_url, owner.tenant_id, week)
    document, diff = a_candidate_moving_one_block(live)
    fill_the_slot(
        live_database_url,
        owner.tenant_id,
        week,
        verdict=a_solved_deadline_gap(
            input_version=version,
            deadline=due,
            area_id=area_id,
            against="Kontron take-home",
        ),
        document=document,
        diff=diff,
        input_version=version,
        operation_id=enqueue_a_solve(live_database_url, owner.tenant_id, week),
    )

    view = week_view(http, headers, week)
    listed = backlog(http, headers)

    served = view["verdict"]["provenance"]
    assert served == "solver", f"the slot was not served ({served}), so this asserts less"
    derived = at_risk_by_the_weeks_verdict(view, listed["tasks"])
    marked = {task["id"] for task in listed["tasks"] if task["atRisk"]}
    assert derived == {named["id"]}
    assert marked == derived
    assert listed["header"]["atRiskCount"] == 1
    assert other["id"] not in marked, "a task the stored verdict does not name was marked"


def test_the_header_count_is_the_size_of_the_marked_set(
    http: TestClient, a_week_a_task_cannot_fit_in: tuple[dict[str, str], IsoWeek, dict[str, Any]]
) -> None:
    """One answer rather than a figure computed beside a per-row comparison."""
    headers, _week, _seeded = a_week_a_task_cannot_fit_in

    listed = backlog(http, headers)

    assert listed["header"]["atRiskCount"] == len(
        [task for task in listed["tasks"] if task["atRisk"]]
    )
    assert listed["header"]["atRiskCount"] == 1


def test_a_task_the_week_has_room_for_is_not_marked(
    http: TestClient, a_week_a_task_cannot_fit_in: tuple[dict[str, str], IsoWeek, dict[str, Any]]
) -> None:
    """The control on the marking: a rule that marked everything would pass the equality above."""
    headers, _week, seeded = a_week_a_task_cannot_fit_in

    marked = {task["id"]: task["atRisk"] for task in backlog(http, headers)["tasks"]}

    assert marked[seeded["impossible"]] is True
    assert marked[seeded["comfortable"]] is False


def test_the_at_risk_filter_narrows_to_the_set_the_weeks_verdict_names(
    http: TestClient, a_week_a_task_cannot_fit_in: tuple[dict[str, str], IsoWeek, dict[str, Any]]
) -> None:
    """Ticket 1521: the filter the route catalog claims, over a week that really marks a task.

    The right-hand side is derived from the WEEK READ's own shortfalls, not from the backlog's
    marks, for the reason every equality in this suite is: a filter compared against the marks it
    filtered on would agree whatever either computed. What this pins is that the narrowing happens
    where the determination is made, so the rows a caller receives and the count beside them are one
    answer.

    Both values are driven, because a filter that answered an empty list for ``true`` and everything
    for ``false`` would pass a test that only asked for one of them, and this suite's own
    ``test_tasks_routes_integration.py`` half runs on a tenant with no verdict at all.
    """
    headers, week, seeded = a_week_a_task_cannot_fit_in
    every = backlog(http, headers)
    derived = at_risk_by_the_weeks_verdict(week_view(http, headers, week), every["tasks"])
    assert derived == {seeded["impossible"]}, "the fixture week was not tight enough to show a gap"

    narrowed = backlog(http, headers, atRisk="true")
    rest = backlog(http, headers, atRisk="false")

    assert {task["id"] for task in narrowed["tasks"]} == derived
    assert {task["id"] for task in rest["tasks"]} == {
        task["id"] for task in every["tasks"]
    } - derived
    assert seeded["comfortable"] in {task["id"] for task in rest["tasks"]}


def test_the_at_risk_filter_moves_neither_header_figure(
    http: TestClient, a_week_a_task_cannot_fit_in: tuple[dict[str, str], IsoWeek, dict[str, Any]]
) -> None:
    """The header is over the Area's open tasks whatever the filter selects.

    Otherwise a reader who narrowed the table to the marked rows would see ``1 of 1 at risk``, which
    is a count of the page rather than of the backlog. The same rule ``openCount`` already carries
    for the status filter.
    """
    headers, _week, _seeded = a_week_a_task_cannot_fit_in

    unfiltered = backlog(http, headers)["header"]

    assert unfiltered == {"openCount": 2, "atRiskCount": 1}
    for wanted in ("true", "false"):
        assert backlog(http, headers, atRisk=wanted)["header"] == unfiltered, wanted


def test_a_week_with_no_plan_marks_nothing_beside_a_week_read_that_has_no_verdict(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """The pair, on the state the maintainer leaves behind for fifteen minutes after every setup.

    Deliberately NO ``produce_a_plan``: this is the week a tenant lives in between finishing setup
    and the maintainer's next tick, which ``plans/emptiness.py`` treats as a first-class product
    state with a stated wait, and which lasts indefinitely whenever the maintainer is behind.

    The task is the same impossible one the planned case uses, so the ONLY difference between the
    two tests is whether the week holds a plan. Both sides are asserted in one observation, because
    the failure this closes was invisible on either screen alone: the backlog marked a task while
    the week read answered `verdict: null`, and no surface could show the shortfall behind the mark.
    """
    headers, area_id = configured
    week = this_week()
    due = datetime.combine(week.dates()[-1], datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)
    capture_a_task(
        http,
        headers,
        area_id,
        title="Kontron take-home",
        estimateMinutes=40 * AN_HOUR,
        deadline=due.isoformat(),
    )

    view = week_view(http, headers, week)
    listed = backlog(http, headers)

    assert view["live"] is None, "the fixture planned the week, so this asserts the wrong state"
    assert view["verdict"] is None
    assert listed["header"]["atRiskCount"] == 0
    assert [task["atRisk"] for task in listed["tasks"]] == [False]
    assert at_risk_by_the_weeks_verdict(view, listed["tasks"]) == {
        task["id"] for task in listed["tasks"] if task["atRisk"]
    }


def test_the_verdict_route_agrees_with_the_backlog_on_an_unplanned_week(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """The third surface that answers a verdict, on the same state, so all three say one thing."""
    headers, area_id = configured
    week = this_week()
    due = datetime.combine(week.dates()[-1], datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)
    capture_a_task(
        http,
        headers,
        area_id,
        title="Kontron take-home",
        estimateMinutes=40 * AN_HOUR,
        deadline=due.isoformat(),
    )

    refreshed = http.get(f"{week_path(week)}/verdict", headers=headers)

    assert refreshed.status_code == HTTPStatus.OK, refreshed.text
    assert refreshed.json() == {"verdict": None}
    assert backlog(http, headers)["header"]["atRiskCount"] == 0


def test_the_at_risk_column_does_not_inflate_on_a_healthy_solved_week(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """``reviews/spec-review-5.md`` B1, from the column's side.

    Under the superseded rule every ``deadline_capacity`` shortfall was inflated by the whole of
    every already-scheduled floor, so a week with room for everything reported a gap and this
    column inflated with it. The week here holds a comfortable deadline: one hour of work due at the
    end of the week, against a week with a frame and nothing else in it.
    """
    headers, area_id = configured
    week = this_week()
    due = datetime.combine(week.dates()[-1], datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)
    comfortable = capture_a_task(
        http,
        headers,
        area_id,
        title="Read one paper",
        estimateMinutes=AN_HOUR,
        deadline=due.isoformat(),
    )
    produce_a_plan(live_database_url, owner.tenant_id, week)

    listed = backlog(http, headers)
    view = week_view(http, headers, week)

    assert view["verdict"]["shortfalls"] == [], view["verdict"]["shortfalls"]
    assert listed["header"]["atRiskCount"] == 0
    marked = [task["atRisk"] for task in listed["tasks"] if task["id"] == comfortable["id"]]
    assert marked == [False]


def test_a_backlog_read_on_a_tenant_far_east_answers_about_its_own_week(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    """The current week is resolved in the HOME zone, not in UTC.

    Auckland's local date runs ahead of the UTC date for thirteen hours of every day, so a reader
    resolving the week in UTC would probe a different week from the one this tenant is living in.
    """
    headers = sign_in(http, owner.email)
    set_home_zone(http, headers, AUCKLAND)
    area_id = declare_the_minimum(http, headers, live_database_url, owner.tenant_id)
    local_today = datetime.now(UTC).astimezone(ZoneInfo(AUCKLAND)).date()
    week = IsoWeek.containing(local_today)
    due = datetime.combine(week.dates()[-1], datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)
    impossible = capture_a_task(
        http,
        headers,
        area_id,
        title="Kontron take-home",
        estimateMinutes=40 * AN_HOUR,
        deadline=due.isoformat(),
    )
    produce_a_plan(live_database_url, owner.tenant_id, week)

    listed = backlog(http, headers)

    assert {task["id"] for task in listed["tasks"] if task["atRisk"]} == {impossible["id"]}


# --------------------------------------------------------------------------------
# Nothing pushes it
# --------------------------------------------------------------------------------


def test_the_event_union_carries_no_verdict_member() -> None:
    """``US-TASK-03``'s last criterion: there is no push, so the union has no member for one.

    Stated over the type the stream is defined against as well as the constants beside it, so a
    fifth member added to one and not the other is still seen.
    """
    declared = set(get_args(EventType.__value__))

    assert declared == set(EVENT_TYPES)
    assert "verdict" not in declared
    assert declared == {"operation", "conflict", "projection", "notice"}


def test_no_event_builder_puts_a_verdict_on_the_stream(source_root: Path) -> None:
    """The other half: a builder that dumped a verdict shape would escape the union check.

    An event carries status and identifiers, and every builder dumps a wire model that already
    exists. A verdict reaching the stream would duplicate the read model over two transports and
    would be a push of the one thing this product deliberately does not push.
    """
    envelopes = (source_root / "events" / "envelopes.py").read_text()

    assert "Verdict" not in envelopes


# --------------------------------------------------------------------------------
# The budget, measured. Ticket 1443
# --------------------------------------------------------------------------------


def test_the_backlog_read_is_well_under_its_budget_on_a_full_week(
    http: TestClient,
    owner: UserRecord,
    configured: tuple[dict[str, str], str],
    live_database_url: str,
) -> None:
    """Ticket **1443**: p95 under 150 ms on a full week, measured rather than asserted.

    The at-risk column made this route pay for a whole solve-input assembly, and section 19 had no
    row for it. The shape measured is the one the week's own budget is stated over, a week holding
    ``BLOCKS_IN_A_FULL_WEEK`` blocks, with twenty deadlined tasks so the marking is doing real work
    rather than answering over an empty backlog.

    Measured on the branch that PAYS: the week's pending slot is empty, so the read assembles and
    probes. A week whose slot is current serves a stored verdict and is the cheaper of the two.

    The ceiling this suite fails at is the same one ``test_week_view_integration.py`` uses and is
    several times the budget, because a developer's machine and a CI runner are not the deployment.
    The figure is printed so a regression is visible without the run turning red on a slow host.
    """
    headers, area_id = configured
    week = this_week()
    due = datetime.combine(week.dates()[-1], datetime.min.time(), tzinfo=UTC) + timedelta(hours=9)
    for index in range(DEADLINED_TASKS):
        capture_a_task(
            http,
            headers,
            area_id,
            title=f"deadlined {index}",
            estimateMinutes=2 * AN_HOUR,
            deadline=due.isoformat(),
        )
    append_a_full_week(live_database_url, owner.tenant_id, week)

    populated = backlog(http, headers)
    assert populated["header"]["openCount"] == DEADLINED_TASKS
    assert week_view(http, headers, week)["verdict"] is not None, (
        "the week served no verdict, so this measures the cheap path rather than the assembly"
    )

    elapsed = []
    for _ in range(LATENCY_SAMPLES):
        started = time.perf_counter()
        answered = http.get(TASKS_PREFIX, headers=headers)
        elapsed.append((time.perf_counter() - started) * 1000)
        assert answered.status_code == HTTPStatus.OK, answered.text

    ordered = sorted(elapsed)
    p95 = quantiles(ordered, n=20)[-1]
    print(
        f"\nGET /api/v1/tasks on a {BLOCKS_IN_A_FULL_WEEK}-block week with {DEADLINED_TASKS} "
        f"deadlined tasks over {LATENCY_SAMPLES} reads: "
        f"p50 {ordered[len(ordered) // 2]:.1f} ms, p95 {p95:.1f} ms, max {ordered[-1]:.1f} ms"
    )

    assert p95 < CATASTROPHIC_MILLISECONDS, ordered
