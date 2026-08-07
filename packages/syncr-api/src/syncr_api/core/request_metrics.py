"""The three HTTP families and the middleware that records them.

Section 18 names ``syncr_http_request_duration_seconds``, ``syncr_http_requests_total`` and
``syncr_http_errors_total``. They sit here rather than beside the ``/metrics`` exposition because
the exposition RENDERS a registry and this RECORDS onto one, and the two change on different
schedules.

**Pure ASGI, for the reason ``CorrelationMiddleware`` is.** A ``BaseHTTPMiddleware`` runs the
handler in a separate contextvars context, and this middleware reads a value an exception handler
wrote onto the request's own scope. Pure ASGI keeps them in one context.

## The route label is the TEMPLATE, and an unmatched path is one series

``/api/v1/weeks/2026-W07`` and ``/api/v1/weeks/2026-W08`` are one route. Labelling by the raw path
would grow a series per week the user ever opens, and a client probing random paths would grow one
per probe, which is the failure mode that turns a metrics endpoint into the memory leak it was added
to detect.

Resolving that template is not a one-liner. A feature router is included INTO a feature router with
a prefix, so the route object the framework puts on the scope carries the inner path only: the areas
collection is ``""`` on that object and the week read is ``/{iso_week}``. Two collections sharing an
inner path would collapse onto one series, and ``""`` names nothing at all. The effective path lives
on the route table's expanded view, so the middleware maps each route object to its own full path
and looks the scope's route up in it. ``test_request_metrics`` crosses that map against the app's
route table in both directions, so a framework change that broke the resolution fails a gate rather
than quietly labelling every request ``unmatched``.

## Why the error family is not seeded

``verdict_metrics`` seeds every series its family can hold, so an absent series and a zero one are
distinguishable. That argument applies to a bounded vocabulary. Here the label set is a PRODUCT of
every route and every problem type, so seeding it would export thousands of zero series to say that
nothing has failed. Absence is left to mean "no error has been recorded", and the alert rules that
read these families are written so an absent series does not read as a healthy one.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final

from prometheus_client import Counter, Histogram

from syncr_api.core.errors import InternalError
from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from starlette.routing import BaseRoute
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

# What the route label carries for a request that matched no route. One series for every 404 a
# scanner can produce, rather than one per path it tried.
UNMATCHED_ROUTE: Final = "unmatched"

# What the problem-type label carries for an error response that is not problem details. `/readyz`
# answers 503 with a readiness body, so the family counts it under a name rather than dropping it:
# a 503 nothing counted is a 503 nothing alerts on.
UNCLASSIFIED_PROBLEM: Final = "unclassified"

# What a request that produced no response at all is recorded as. A client that disconnected mid
# request is not syncr failing, so it carries a status class of its own rather than folding into the
# 5xx class an operator reads as a fault. It is still recorded: a request nothing counted is a
# request no latency series can see.
DISCONNECTED_STATUS_CLASS: Final = "disconnected"
DISCONNECTED_PROBLEM: Final = "client-disconnected"

# The scope key an exception handler writes the rendered problem's type onto. `Request.state` is
# backed by `scope["state"]`, so a handler running inside this middleware can hand a value out to
# it without the middleware parsing the response body.
PROBLEM_TYPE_STATE_KEY: Final = "problem_type"

REQUEST_DURATION = Histogram(
    "syncr_http_request_duration_seconds",
    "Latency of one HTTP request in seconds, by route template, method and status class.",
    labelnames=("route", "method", "status_class"),
    registry=REGISTRY,
)

REQUESTS = Counter(
    "syncr_http_requests_total",
    "HTTP requests served, by route template, method and status class.",
    labelnames=("route", "method", "status_class"),
    registry=REGISTRY,
)

ERRORS = Counter(
    "syncr_http_errors_total",
    "HTTP responses at 400 or above, by route template and the problem type sent.",
    labelnames=("route", "problem_type"),
    registry=REGISTRY,
)

# The lowest status this application treats as an error response.
ERROR_STATUS_FLOOR: Final = 400


def status_class(status: int | None) -> str:
    """``2xx`` for 200, ``4xx`` for 404, and its own class for a request that never answered.

    Five values, so the label set cannot grow. The fifth exists because a client disconnect and a
    server fault are different events and only one of them is syncr's.
    """
    return DISCONNECTED_STATUS_CLASS if status is None else f"{status // 100}xx"


class RequestMetricsMiddleware:
    """Record every HTTP request's latency, its count, and its error under the route template.

    ``routes`` is the live route table the app was assembled from, so the template map is built
    from whatever routes exist rather than from a list someone maintains. It is read on first use
    rather than at construction, because middleware is instantiated while the app is still being
    built.
    """

    def __init__(self, app: ASGIApp, *, routes: Iterable[BaseRoute]) -> None:
        self.app = app
        # Held for the app's whole life, which is what makes the identity map below safe: every
        # key is the id of a route this list still references, so no id can be reused.
        self._routes = routes
        self._templates: Mapping[int, str] | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        # A response that never starts is a client that disconnected mid request, and it is recorded
        # under a status class of its own: a request nothing counted is a request no latency series
        # can see, and folding it into the 5xx class would read as syncr failing.
        seen = _StatusHolder()
        try:
            await self.app(scope, receive, _watching(send, seen))
        except Exception:
            # The catch-all handler that renders this as `syncr:internal-error` is mounted OUTSIDE
            # every user middleware, so its problem type never reaches the scope this reads. The
            # request is classified here from the same constant that handler renders, rather than
            # being counted as an error of unknown kind.
            self._recorded(
                scope,
                seen.status if seen.status is not None else 500,
                time.perf_counter() - started,
                problem=InternalError.type,
            )
            raise
        self._recorded(scope, seen.status, time.perf_counter() - started)

    def _recorded(
        self, scope: Scope, status: int | None, elapsed: float, *, problem: str | None = None
    ) -> None:
        route = self._template(scope)
        labels = {"route": route, "method": scope["method"], "status_class": status_class(status)}
        REQUEST_DURATION.labels(**labels).observe(elapsed)
        REQUESTS.labels(**labels).inc()
        if status is None:
            ERRORS.labels(route=route, problem_type=DISCONNECTED_PROBLEM).inc()
        elif status >= ERROR_STATUS_FLOOR:
            ERRORS.labels(route=route, problem_type=problem or _problem_type(scope)).inc()

    def _template(self, scope: Scope) -> str:
        """This route's full path template, or the fixed label for a request that matched none."""
        if self._templates is None:
            self._templates = templates_by_route(self._routes)
        matched = scope.get("route")
        return self._templates.get(id(matched), UNMATCHED_ROUTE) if matched else UNMATCHED_ROUTE


class _StatusHolder:
    """The response status, captured as the response starts. ``None`` until one does."""

    def __init__(self) -> None:
        self.status: int | None = None


def _watching(send: Send, seen: _StatusHolder) -> Send:
    async def send_and_record(message: Message) -> None:
        if message["type"] == "http.response.start":
            seen.status = int(message["status"])
        await send(message)

    return send_and_record


def templates_by_route(routes: Iterable[BaseRoute]) -> Mapping[int, str]:
    """Each route mapped to the full path it answers on, keyed by the route's identity.

    The route object the framework puts on the scope is the key, valued by the path from the route
    table's expanded view, which is the only one carrying the prefixes the route was included under.

    Keyed by ``id`` because a Starlette route defines equality without a hash, so it cannot be a
    dictionary key. The caller holds the route table for the app's whole life, so an id in this map
    always names the route it was built from.

    Exported so a test can cross this map against the app's own route table.
    """
    found: dict[int, str] = {}
    for expanded in _expanded(routes):
        route = getattr(expanded, "original_route", expanded)
        path = getattr(expanded, "path", None)
        if isinstance(path, str) and path:
            found[id(route)] = path
    return found


def _expanded(routes: Iterable[BaseRoute]) -> Iterable[object]:
    """Flatten an included router into the routes it contributes, at every depth."""
    for route in routes:
        expand = getattr(route, "effective_route_contexts", None)
        if callable(expand):
            # Recurses through nested includes on its own, so one level here is enough.
            yield from expand()
        else:
            yield route


def _problem_type(scope: Scope) -> str:
    """The problem type an exception handler recorded for this request, or the fixed label."""
    state = scope.get("state") or {}
    recorded = state.get(PROBLEM_TYPE_STATE_KEY)
    return recorded if isinstance(recorded, str) else UNCLASSIFIED_PROBLEM
