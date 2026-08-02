"""The ``/metrics`` exposition endpoint.

The registry and the per-method decorator live in ``syncr_common.metrics``, which
carries no web stack so the offline learning job can measure its own fitters.
Serving that registry over HTTP is the api's job, and this is where it happens.
Reachable only inside ``app-net``.

Ticket-owned HTTP request families (route latency, request counts, error counts by
problem type) are added here alongside the exposition when the observability slice
lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter
from starlette.responses import Response

from syncr_common.metrics import render

if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry

METRICS_ENDPOINT = "/metrics"


def create_metrics_router(registry: CollectorRegistry | None = None) -> APIRouter:
    """Build the ``/metrics`` router over ``registry``, defaulting to syncr's own."""
    router = APIRouter(tags=["observability"])

    @router.get(METRICS_ENDPOINT, include_in_schema=False)
    async def metrics() -> Response:
        payload, content_type = render(registry)
        return Response(content=payload, media_type=content_type)

    return router
