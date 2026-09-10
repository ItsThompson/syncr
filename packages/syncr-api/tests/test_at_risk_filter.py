"""The at-risk filter the route declares, over a stated verdict and no database.

Two halves of one claim are asserted together here, because each alone is weaker than it looks.
The route advertises a query parameter with three values and a promise about the header. The
service narrows over the set it derived from the week's verdict. What a caller receives has to be
the answer the advertisement describes, and that is a statement about both.

**The verdict is stated rather than assembled**, so the marked task is known before the request is
made. Nothing about the two tasks separates them for this purpose: both are open, both are due at
the same instant, and both owe the same work. Only the verdict names one. A narrowing recomputed
from the rows would have to answer both or neither.

They are captured at different instants, because the list is oldest first and an order the row
identifiers decide is an order that changes between runs.

The same filter over a real week whose deadline cannot be met is driven in
``test_at_risk_integration.py``, against the week read's own shortfalls. This module needs no
Postgres and no plan, so the three values are driven whatever week the suite is run in.

The fakes and the scene builders are the Task service suite's, imported rather than copied: a
second set of repository fakes would be a second answer to what the read path reaches.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.injection import require_client_principal
from syncr_api.core.app_factory import create_app
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES
from syncr_api.tasks.config import TASKS_PREFIX
from syncr_api.tasks.injection import get_task_service
from syncr_api.tasks.wiring import build_tasks_router
from tests.service_builders import a_task, an_area
from tests.test_tasks_service import (
    A_DEADLINE,
    LATER,
    RecordingWeekInputVersions,
    a_deadline_gap,
    a_verdict,
    build,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

    from syncr_api.core.settings import ServiceSettings
    from syncr_api.tasks.records import TaskRecord

# The clause the parameter's own description states about the header, quoted so the promise and the
# served answer are asserted in one place. A reader who narrows the table to the marked rows must
# not see a count of the page: the count and the marked rows are one answer or they disagree.
HEADER_PROMISE = "both header figures are over the Area's open tasks whatever this is set to"

MARKED_TITLE = "Leetcode"
UNMARKED_TITLE = "Mock interview"


@pytest.fixture
def principal() -> Principal:
    return Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=ALL_SCOPES)


def tasks_app(settings: ServiceSettings) -> FastAPI:
    """The backlog routes alone, which is every route the filter is declared on."""
    return create_app(settings, feature_routers=(build_tasks_router,))


@pytest.fixture
def scene(
    settings: ServiceSettings, principal: Principal
) -> Iterator[tuple[TestClient, TaskRecord, TaskRecord]]:
    """Two tasks nothing but a verdict tells apart, and the one of them it names."""
    area = an_area(principal.tenant_id)
    named = a_task(principal.tenant_id, area.id, title=MARKED_TITLE, deadline=A_DEADLINE)
    other = a_task(
        principal.tenant_id,
        area.id,
        title=UNMARKED_TITLE,
        deadline=A_DEADLINE,
        created_at=LATER,
    )
    service, _ = build(
        principal,
        RecordingWeekInputVersions(),
        areas=[area],
        tasks=[named, other],
        verdict=a_verdict(a_deadline_gap(MARKED_TITLE, area_id=area.id)),
    )
    app = tasks_app(settings)
    app.dependency_overrides[require_client_principal] = lambda: principal
    app.dependency_overrides[get_task_service] = lambda: service
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, named, other


def read(client: TestClient, at_risk: str | None = None) -> dict[str, Any]:
    """One backlog read, with the filter spelled the way the route publishes it."""
    answered = client.get(TASKS_PREFIX, params={} if at_risk is None else {"atRisk": at_risk})
    assert answered.status_code == HTTPStatus.OK, answered.text
    payload: dict[str, Any] = answered.json()
    return payload


def titles(answered: dict[str, Any]) -> list[str]:
    return [task["title"] for task in answered["tasks"]]


def the_at_risk_parameter(app: FastAPI) -> dict[str, Any]:
    """The parameter as the generated document advertises it."""
    declared = app.openapi()["paths"][TASKS_PREFIX]["get"]["parameters"]
    (parameter,) = [one for one in declared if one["name"] == "atRisk"]
    found: dict[str, Any] = parameter
    return found


def test_each_of_the_three_declared_values_answers_a_distinguishable_set(
    scene: tuple[TestClient, TaskRecord, TaskRecord],
) -> None:
    """True, false and absent are three questions, and no two of them share an answer.

    Driven over a population the verdict really does split, because the three collapse into two on
    a week that marks nothing: an empty marked set makes false and absent the same answer, and a
    filter that narrowed to nothing at all would pass a suite that only asked for the rest.
    """
    client, _named, _other = scene

    every = read(client)
    marked = read(client, "true")
    rest = read(client, "false")

    assert titles(every) == [MARKED_TITLE, UNMARKED_TITLE]
    assert titles(marked) == [MARKED_TITLE]
    assert titles(rest) == [UNMARKED_TITLE]


def test_the_rows_the_filter_admits_are_the_rows_the_marked_column_names(
    scene: tuple[TestClient, TaskRecord, TaskRecord],
) -> None:
    """The filter and the column are one derivation, so a row cannot be marked and filtered out.

    Both are read from the same answer here, and what makes that more than a comparison of a set
    against itself is the fixture: the verdict names one title, so the expected side of both
    assertions is known before the request.
    """
    client, named, other = scene

    every = read(client)

    assert {task["id"]: task["atRisk"] for task in every["tasks"]} == {
        str(named.id): True,
        str(other.id): False,
    }
    assert titles(read(client, "true")) == [
        task["title"] for task in every["tasks"] if task["atRisk"]
    ]


def test_the_header_promise_the_document_advertises_is_the_one_the_route_serves(
    settings: ServiceSettings, scene: tuple[TestClient, TaskRecord, TaskRecord]
) -> None:
    """The description's answer to the header question, asserted rather than merely published.

    The clause is read out of the generated document and the figures are read off three requests,
    so a description that stopped being true is a failure here rather than a sentence nobody
    checks.
    """
    client, _named, _other = scene

    advertised = the_at_risk_parameter(tasks_app(settings))["description"]
    served = [read(client, wanted)["header"] for wanted in (None, "true", "false")]

    assert HEADER_PROMISE in advertised
    assert served == [{"openCount": 2, "atRiskCount": 1}] * 3


def test_the_document_declares_a_filter_that_can_be_left_unstated(
    settings: ServiceSettings,
) -> None:
    """The third value is the absent one, so the parameter is optional and nullable.

    A required parameter, or one defaulted to false, would answer the rest of the backlog to a
    caller that asked no question at all.
    """
    parameter = the_at_risk_parameter(tasks_app(settings))

    assert parameter["in"] == "query"
    assert parameter["required"] is False
    assert {"type": "boolean"} in parameter["schema"]["anyOf"]
    assert {"type": "null"} in parameter["schema"]["anyOf"]
