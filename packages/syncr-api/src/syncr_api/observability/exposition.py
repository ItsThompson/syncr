"""The worker's Prometheus exposition, because a process with no HTTP surface cannot be scraped.

The api serves ``/metrics`` over the api's registry. The worker holds a registry of its own, in its
own process, and until this module existed nothing served it: every solve, materialization, verdict
transition, projection, calendar sync and horizon reading is recorded in the worker, so the whole
plan pipeline was instrumented and unreadable. That is not a family with no alert; it is an entire
subsystem with no scrape.

A thread rather than an event loop. The client library ships a WSGI exposition and a
``start_http_server`` that runs it on a daemon thread, so the worker's loop does not share its
thread with a scrape and needs no ASGI stack. Reading a registry is a snapshot of counters and
gauges, which is safe to do from another thread.

Bound inside ``app-net`` only, like the api's, and on a port of its own so one Prometheus job can
scrape each process separately: a figure that arrived from either process would make "which one
stopped" unanswerable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from prometheus_client import start_http_server

from syncr_common.logging import get_logger
from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry

# The worker's exposition port. Not 8000: the api holds that, and both run on `app-net`.
WORKER_METRICS_PORT: Final = 9100

_log = get_logger("syncr.observability")


def serve_worker_metrics(
    *, port: int = WORKER_METRICS_PORT, registry: CollectorRegistry | None = None
) -> int:
    """Start the exposition on a daemon thread and answer with the port it bound.

    The port is returned rather than assumed, so a caller that passed zero (a test wanting whatever
    is free) knows where to scrape. Failure to bind is fatal by design: a worker whose metrics
    nobody can read is a worker whose failures nobody can see, and starting anyway would hide that
    behind a log line.
    """
    server, _thread = start_http_server(port, registry=registry or REGISTRY)
    bound = int(server.server_port)
    _log.info("observability.exposition.started", port=bound)
    return bound
