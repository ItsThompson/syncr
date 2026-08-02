"""The per-method decorator and the ``/metrics`` exposition."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from syncr_common.metrics import (
    METRICS_ENDPOINT,
    REGISTRY,
    create_metrics_router,
    measured,
    render,
)

COMPONENT = "test_component"


def _duration_count(method: str) -> float:
    sample = REGISTRY.get_sample_value(
        "syncr_method_duration_seconds_count", {"component": COMPONENT, "method": method}
    )
    return sample or 0.0


def _error_count(method: str) -> float:
    sample = REGISTRY.get_sample_value(
        "syncr_method_errors_total", {"component": COMPONENT, "method": method}
    )
    return sample or 0.0


def test_sync_method_records_latency_and_returns_its_result() -> None:
    @measured(COMPONENT)
    def assemble(week: str) -> str:
        return f"inputs for {week}"

    before = _duration_count("assemble")

    assert assemble("2026-W07") == "inputs for 2026-W07"
    assert _duration_count("assemble") == before + 1
    assert _error_count("assemble") == 0


async def test_async_method_records_latency_and_returns_its_result() -> None:
    @measured(COMPONENT)
    async def probe(week: str) -> bool:
        return week == "2026-W07"

    before = _duration_count("probe")

    assert await probe("2026-W07") is True
    assert _duration_count("probe") == before + 1


def test_sync_failure_counts_an_error_and_re_raises() -> None:
    @measured(COMPONENT)
    def commit() -> None:
        raise RuntimeError("write guard mismatch")

    with pytest.raises(RuntimeError, match="write guard mismatch"):
        commit()

    assert _error_count("commit") == 1
    # The latency observation still happens, so an error rate is a ratio against
    # the histogram's own count.
    assert _duration_count("commit") == 1


async def test_async_failure_counts_an_error_and_re_raises() -> None:
    @measured(COMPONENT)
    async def solve() -> None:
        raise ValueError("infeasible")

    with pytest.raises(ValueError, match="infeasible"):
        await solve()

    assert _error_count("solve") == 1
    assert _duration_count("solve") == 1


def test_decorator_preserves_the_wrapped_identity() -> None:
    @measured(COMPONENT)
    def materialize() -> None:
        """Place what derivation determines."""

    assert materialize.__name__ == "materialize"
    assert materialize.__doc__ == "Place what derivation determines."


def test_render_serves_the_declared_families() -> None:
    @measured(COMPONENT)
    def classify() -> None:
        """Partition a candidate plan's diff."""

    classify()
    payload, content_type = render()

    assert b"syncr_method_duration_seconds" in payload
    assert b"syncr_method_errors_total" in payload
    assert "text/plain" in content_type


def test_render_carries_no_client_library_default_families() -> None:
    payload, _ = render()

    assert b"python_gc_objects_collected_total" not in payload
    assert b"process_start_time_seconds" not in payload


def test_metrics_endpoint_serves_prometheus_exposition() -> None:
    app = FastAPI()
    app.include_router(create_metrics_router())

    with TestClient(app) as client:
        response = client.get(METRICS_ENDPOINT)

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "syncr_method_duration_seconds" in response.text


def test_metrics_router_serves_an_injected_registry() -> None:
    private = CollectorRegistry()
    app = FastAPI()
    app.include_router(create_metrics_router(private))

    with TestClient(app) as client:
        response = client.get(METRICS_ENDPOINT)

    assert response.status_code == 200
    assert "syncr_method_duration_seconds" not in response.text
