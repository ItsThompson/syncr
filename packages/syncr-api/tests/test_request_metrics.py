"""The three HTTP families, read out of the exposition a scraper reads.

Every assertion here goes through ``GET /metrics``, not through a private attribute of a collector.
A family a unit test can see and a scrape cannot is a family no alert can read.

**Read as a DELTA, never as an absolute.** The registry is process-wide and every other module in
this suite serves requests onto it, so a test asserting an absolute count would pass or fail on
collection order. Each test takes a reading, acts, and asserts what its own action added.

Each failing case BREAKS something and watches the counter move: a route that raises, a path that
matches nothing, and a refused request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from syncr_api.core.app_factory import create_app
from syncr_api.core.errors import Conflict, NotFound
from syncr_api.core.observability import METRICS_ENDPOINT
from syncr_api.core.request_metrics import (
    UNCLASSIFIED_PROBLEM,
    UNMATCHED_ROUTE,
    status_class,
    templates_by_route,
)
from syncr_common.health import HEALTHZ_ENDPOINT, READYZ_ENDPOINT
from tests.boundaries import api_routes
from tests.conftest import failing_check

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

    from syncr_api.core.settings import ServiceSettings

PROBE_PATH = "/probe/{name}"
RAISING_PATH = "/probe-raising"
REFUSED_PATH = "/probe-refused"
# A prefix the probe router is included UNDER, so these tests drive the two-level shape every
# feature module uses rather than the one-level shape only the health routes have.
PROBE_PREFIX = "/probe-collection"

REQUESTS = "syncr_http_requests_total"
ERRORS = "syncr_http_errors_total"
DURATION_COUNT = "syncr_http_request_duration_seconds_count"
DURATION_SUM = "syncr_http_request_duration_seconds_sum"


def _probe_router() -> APIRouter:
    """Routes that answer, raise a mapped error, and raise an unmapped one.

    Included under a prefix by :func:`_prefixed_router`, so the paths declared here are the INNER
    ones and the label under test is the full path.
    """
    router = APIRouter()

    @router.get(RAISING_PATH)
    async def raising() -> JSONResponse:
        raise RuntimeError("a fault no handler maps")

    @router.get(REFUSED_PATH)
    async def refused() -> JSONResponse:
        raise Conflict("this week already holds a proposal")

    @router.get(PROBE_PATH)
    async def probe(name: str) -> JSONResponse:
        if name == "missing":
            raise NotFound("no such thing")
        return JSONResponse({"name": name})

    return router


def _prefixed_router() -> APIRouter:
    router = APIRouter()
    router.include_router(_probe_router(), prefix=PROBE_PREFIX)
    return router


def full(path: str) -> str:
    """The full path a probe route answers on, which is what the route label must carry."""
    return f"{PROBE_PREFIX}{path}"


@pytest.fixture
def instrumented(settings: ServiceSettings) -> Iterator[TestClient]:
    """A client over an app carrying only the probe router, so route labels are this module's."""
    app = create_app(settings, feature_routers=(_prefixed_router,))
    with TestClient(app, raise_server_exceptions=False) as http:
        yield http


def sample(client: TestClient, name: str, **labels: str) -> float:
    """One sample's value out of the exposition, matched on the full label set. Zero if absent.

    Parsed from the text a scraper reads rather than from the collector, so a family the registry
    holds but the exposition does not would fail here. Absent reads as zero because these tests
    measure a delta, and a series that does not exist yet has contributed nothing.
    """
    wanted = ",".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
    prefix = f"{name}{{{wanted}}} "
    for line in client.get(METRICS_ENDPOINT).text.splitlines():
        if line.startswith(prefix):
            return float(line.removeprefix(prefix))
    return 0.0


def exposition(client: TestClient) -> str:
    """The exposition body, as a scraper receives it."""
    return str(client.get(METRICS_ENDPOINT).text)


class TestTheTemplateMap:
    """The map is crossed against the app's own route table, in both directions.

    Bounded by the route table rather than by a list, so a route added by a later feature module is
    covered without this test being touched. Both directions matter: a route with no template would
    be labelled ``unmatched``, and a template naming no route would mean the map was built from
    something other than the routes being served.
    """

    def test_every_route_the_app_declares_has_a_full_template(self, app: FastAPI) -> None:
        declared = {route.path for route in api_routes(app)}
        resolved = set(templates_by_route(app.routes).values())

        assert declared <= resolved

    def test_it_names_no_path_the_app_does_not_serve(self, app: FastAPI) -> None:
        declared = {route.path for route in api_routes(app)} | {
            HEALTHZ_ENDPOINT,
            READYZ_ENDPOINT,
            METRICS_ENDPOINT,
        }
        resolved = set(templates_by_route(app.routes).values())

        # The framework's own documentation routes are the remainder, and they are served.
        assert resolved - declared <= {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}

    def test_a_route_included_under_a_prefix_resolves_to_the_prefixed_path(
        self, settings: ServiceSettings
    ) -> None:
        """The inner path is what the framework puts on the scope, and it is not the label.

        Without this the areas collection would be labelled ``""`` and every week route
        ``/{iso_week}``.
        """
        app = create_app(settings, feature_routers=(_prefixed_router,))

        resolved = set(templates_by_route(app.routes).values())

        assert full(PROBE_PATH) in resolved
        assert PROBE_PATH not in resolved


class TestTheStatusClass:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [(200, "2xx"), (201, "2xx"), (307, "3xx"), (404, "4xx"), (422, "4xx"), (500, "5xx")],
    )
    def test_it_collapses_a_status_onto_its_class(self, status: int, expected: str) -> None:
        assert status_class(status) == expected

    def test_a_request_that_never_answered_is_its_own_class(self) -> None:
        """A client disconnect and a server fault are different events, and one is not syncr's.

        Folding a disconnect into the 5xx class would put the user closing a laptop lid into the
        series an operator reads as the application failing.
        """
        assert status_class(None) == "disconnected"


class TestTheRouteLabel:
    def test_it_carries_the_template_rather_than_the_path_that_matched_it(
        self, instrumented: TestClient
    ) -> None:
        labels = {"route": full(PROBE_PATH), "method": "GET", "status_class": "2xx"}
        before = sample(instrumented, REQUESTS, **labels)

        instrumented.get(full("/probe/first"))
        instrumented.get(full("/probe/second"))

        text = exposition(instrumented)
        assert sample(instrumented, REQUESTS, **labels) - before == 2.0
        assert "/probe/first" not in text
        assert "/probe/second" not in text

    def test_a_path_that_matches_no_route_is_one_series(self, instrumented: TestClient) -> None:
        labels = {"route": UNMATCHED_ROUTE, "method": "GET", "status_class": "4xx"}
        before = sample(instrumented, REQUESTS, **labels)

        for path in ("/nope", "/also-nope", "/deeply/nested/nope"):
            instrumented.get(path)

        assert sample(instrumented, REQUESTS, **labels) - before == 3.0
        assert "/also-nope" not in exposition(instrumented)


class TestTheLatencyFamily:
    def test_a_served_request_is_counted_and_timed(self, instrumented: TestClient) -> None:
        labels = {"route": full(PROBE_PATH), "method": "GET", "status_class": "2xx"}
        counted = sample(instrumented, DURATION_COUNT, **labels)
        summed = sample(instrumented, DURATION_SUM, **labels)

        instrumented.get(full("/probe/one"))

        assert sample(instrumented, DURATION_COUNT, **labels) - counted == 1.0
        assert sample(instrumented, DURATION_SUM, **labels) > summed

    def test_the_metrics_endpoint_records_itself(self, instrumented: TestClient) -> None:
        """The exposition is a request, so the scrape that reads it is recorded too.

        Asserted because a middleware that skipped it would leave the one route Prometheus calls
        most often invisible.
        """
        labels = {"route": METRICS_ENDPOINT, "method": "GET", "status_class": "2xx"}
        before = sample(instrumented, REQUESTS, **labels)

        # Two scrapes: the second one's body reports the first, which is what a self-recording
        # middleware means. The reading above is itself a scrape, so the delta counts three.
        exposition(instrumented)
        exposition(instrumented)

        assert sample(instrumented, REQUESTS, **labels) - before == 3.0

    def test_a_method_the_route_does_not_serve_is_recorded_under_the_route_it_named(
        self, instrumented: TestClient
    ) -> None:
        """A 405 named a real route, so it is attributed to that route rather than to nothing."""
        labels = {"route": full(REFUSED_PATH), "method": "DELETE", "status_class": "4xx"}
        before = sample(instrumented, REQUESTS, **labels)

        assert instrumented.delete(full(REFUSED_PATH)).status_code == 405

        assert sample(instrumented, REQUESTS, **labels) - before == 1.0


class TestTheErrorFamily:
    def test_a_mapped_error_is_counted_under_the_problem_type_it_sent(
        self, instrumented: TestClient
    ) -> None:
        labels = {"route": full(REFUSED_PATH), "problem_type": "syncr:conflict"}
        before = sample(instrumented, ERRORS, **labels)

        answered = instrumented.get(full(REFUSED_PATH))

        assert answered.json()["type"] == "syncr:conflict"
        assert sample(instrumented, ERRORS, **labels) - before == 1.0

    def test_a_parameterized_route_carries_its_template_on_the_error_too(
        self, instrumented: TestClient
    ) -> None:
        labels = {"route": full(PROBE_PATH), "problem_type": "syncr:not-found"}
        before = sample(instrumented, ERRORS, **labels)

        assert instrumented.get(full("/probe/missing")).status_code == 404

        assert sample(instrumented, ERRORS, **labels) - before == 1.0

    def test_a_fault_no_handler_maps_is_counted_as_an_internal_error(
        self, instrumented: TestClient
    ) -> None:
        """The catch-all renders it outside every user middleware, so the type is derived here.

        Without that, the one failure an operator most needs to see would be counted as an error of
        unknown kind.
        """
        errors = {"route": full(RAISING_PATH), "problem_type": "syncr:internal-error"}
        requests = {"route": full(RAISING_PATH), "method": "GET", "status_class": "5xx"}
        before_errors = sample(instrumented, ERRORS, **errors)
        before_requests = sample(instrumented, REQUESTS, **requests)

        assert instrumented.get(full(RAISING_PATH)).status_code == 500

        assert sample(instrumented, ERRORS, **errors) - before_errors == 1.0
        assert sample(instrumented, REQUESTS, **requests) - before_requests == 1.0

    def test_an_error_response_that_is_not_problem_details_is_still_counted(
        self, settings: ServiceSettings
    ) -> None:
        """A readiness 503 carries a readiness body, not a problem, and must not vanish.

        That is what the fixed label is for: an uncounted 503 is a 503 nothing can alert on.
        """
        app = create_app(
            settings, feature_routers=(), readiness_checks=(failing_check("postgres", "down"),)
        )
        labels = {"route": READYZ_ENDPOINT, "problem_type": UNCLASSIFIED_PROBLEM}
        with TestClient(app, raise_server_exceptions=False) as http:
            before = sample(http, ERRORS, **labels)

            assert http.get(READYZ_ENDPOINT).status_code == 503

            assert sample(http, ERRORS, **labels) - before == 1.0

    def test_a_served_request_records_no_error(self, instrumented: TestClient) -> None:
        labels = {"route": HEALTHZ_ENDPOINT, "problem_type": UNCLASSIFIED_PROBLEM}
        before = sample(instrumented, ERRORS, **labels)

        assert instrumented.get(HEALTHZ_ENDPOINT).status_code == 200

        assert sample(instrumented, ERRORS, **labels) - before == 0.0
