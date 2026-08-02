"""The Prometheus registry and the per-method metric decorator.

One private :class:`CollectorRegistry` holds every syncr family, so ``/metrics``
serves exactly what this application declares and nothing the client library
collects by default. Host and container metrics come from node_exporter and
cadvisor instead.

:func:`measured` is the per-method seam: it records a latency histogram on every
exit and an error counter on a failing one, then re-raises. Wrapping the method
rather than counting at call sites means a failure exit cannot be forgotten, and
the single decorator argument (the component name) keeps the label set bounded to
component plus method.
"""

from __future__ import annotations

import functools
import inspect
import time
from typing import TYPE_CHECKING, ParamSpec, TypeVar, cast

from fastapi import APIRouter
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.responses import Response

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

METRICS_ENDPOINT = "/metrics"

REGISTRY = CollectorRegistry()

METHOD_DURATION = Histogram(
    "syncr_method_duration_seconds",
    "Latency of a decorated method in seconds, by component and method.",
    labelnames=("component", "method"),
    registry=REGISTRY,
)

# Errors carry the same label pair as the histogram and no exception-type label,
# so an error rate is a ratio against the histogram's own count and the label
# cardinality cannot grow with the exception hierarchy.
METHOD_ERRORS = Counter(
    "syncr_method_errors_total",
    "Decorated methods that exited by raising, by component and method.",
    labelnames=("component", "method"),
    registry=REGISTRY,
)

# `measured` returns a generic decorator, so its type variables are declared at
# module scope: a PEP 695 parameter list on `measured` itself would bind them to the
# factory call rather than to the decorated function.
_Params = ParamSpec("_Params")
_Result = TypeVar("_Result")


def measured(component: str) -> Callable[[Callable[_Params, _Result]], Callable[_Params, _Result]]:
    """Decorate a method so every call records latency and every raise records an error.

    Works on both ``def`` and ``async def``. ``component`` names the owning module
    or service (``week_assembler``, ``solve_coordinator``); the method label is the
    decorated function's own name.
    """

    def decorate(fn: Callable[_Params, _Result]) -> Callable[_Params, _Result]:
        if inspect.iscoroutinefunction(fn):
            # `iscoroutinefunction` narrows the runtime type but not the static
            # one, so the awaitable wrapper is re-cast to the decorated signature.
            awaitable_fn = cast("Callable[_Params, Awaitable[_Result]]", fn)
            return cast("Callable[_Params, _Result]", _wrap_async(component, awaitable_fn))
        return _wrap_sync(component, fn)

    return decorate


def _wrap_sync[**P, R](component: str, fn: Callable[P, R]) -> Callable[P, R]:
    labels = {"component": component, "method": fn.__name__}

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        started = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        except Exception:
            METHOD_ERRORS.labels(**labels).inc()
            raise
        finally:
            METHOD_DURATION.labels(**labels).observe(time.perf_counter() - started)

    return wrapper


def _wrap_async[**P, R](component: str, fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    labels = {"component": component, "method": fn.__name__}

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        started = time.perf_counter()
        try:
            return await fn(*args, **kwargs)
        except Exception:
            METHOD_ERRORS.labels(**labels).inc()
            raise
        finally:
            METHOD_DURATION.labels(**labels).observe(time.perf_counter() - started)

    return wrapper


def render(registry: CollectorRegistry | None = None) -> tuple[bytes, str]:
    """The Prometheus text exposition of ``registry`` and its content type."""
    return generate_latest(registry or REGISTRY), CONTENT_TYPE_LATEST


def create_metrics_router(registry: CollectorRegistry | None = None) -> APIRouter:
    """Build the ``/metrics`` router. Reachable only inside ``app-net``."""
    router = APIRouter(tags=["observability"])
    exposed = registry or REGISTRY

    @router.get(METRICS_ENDPOINT, include_in_schema=False)
    async def metrics() -> Response:
        payload, content_type = render(exposed)
        return Response(content=payload, media_type=content_type)

    return router
