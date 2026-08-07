"""``US-TASK-03``: the backlog's at-risk column and the week's verdict are one arithmetic.

The claim is about two SCREENS agreeing, so it cannot be asserted inside either of them. What this
suite drives is the equality between the set the backlog marks and the set derived from the week
read's own shortfalls, over a real week whose deadline really cannot be met.

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

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, get_args
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.events.config import EVENT_TYPES, EventType
from syncr_domain.feasibility import ShortfallKind
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import provision_owner, remove_tenant
from tests.live_weeks import (
    AN_HOUR,
    AUCKLAND,
    LONDON,
    backlog,
    capture_a_task,
    declare_the_minimum,
    produce_a_plan,
    set_home_zone,
    sign_in,
    this_week,
    week_view,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings

pytestmark = pytest.mark.integration


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
