"""The ``/metrics`` exposition endpoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from syncr_api.core.observability import METRICS_ENDPOINT, create_metrics_router


def test_the_endpoint_serves_the_shared_registry() -> None:
    app = FastAPI()
    app.include_router(create_metrics_router())

    with TestClient(app) as client:
        response = client.get(METRICS_ENDPOINT)

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "syncr_method_duration_seconds" in response.text
    assert "syncr_method_errors_total" in response.text


def test_an_injected_registry_is_served_instead() -> None:
    app = FastAPI()
    app.include_router(create_metrics_router(CollectorRegistry()))

    with TestClient(app) as client:
        response = client.get(METRICS_ENDPOINT)

    assert response.status_code == 200
    assert "syncr_method_duration_seconds" not in response.text
