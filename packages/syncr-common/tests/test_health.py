"""The liveness and readiness contract, through a mounted router."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from syncr_common.health import (
    HEALTHZ_ENDPOINT,
    READYZ_ENDPOINT,
    RETRY_AFTER_SECONDS,
    CheckResult,
    ReadinessCheck,
    create_health_router,
)


def passing(name: str) -> ReadinessCheck:
    async def check() -> CheckResult:
        return CheckResult(name=name, ok=True)

    return check


def failing(name: str, detail: str) -> ReadinessCheck:
    async def check() -> CheckResult:
        return CheckResult(name=name, ok=False, detail=detail)

    return check


def raising(detail: str) -> ReadinessCheck:
    async def check() -> CheckResult:
        raise RuntimeError(detail)

    return check


def client(*checks: ReadinessCheck, retry_after_seconds: int = RETRY_AFTER_SECONDS) -> TestClient:
    app = FastAPI()
    app.include_router(create_health_router(checks, retry_after_seconds=retry_after_seconds))
    return TestClient(app)


def test_liveness_answers_200_without_running_any_check() -> None:
    # A liveness probe that fails on a brief dependency outage restarts a healthy
    # process, so a failing dependency must not reach /healthz at all.
    with client(failing("postgres", "connection refused")) as http:
        response = http.get(HEALTHZ_ENDPOINT)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "Retry-After" not in response.headers


def test_readiness_answers_200_when_every_check_passes() -> None:
    with client(passing("postgres"), passing("migrations")) as http:
        response = http.get(READYZ_ENDPOINT)

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["postgres"]["ok"] is True
    assert response.json()["checks"]["migrations"]["ok"] is True


def test_readiness_answers_503_with_retry_after_when_a_check_fails() -> None:
    with client(passing("postgres"), failing("migrations", "head 0002 not applied")) as http:
        response = http.get(READYZ_ENDPOINT)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == str(RETRY_AFTER_SECONDS)
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["migrations"]["detail"] == "head 0002 not applied"


def test_readiness_degrades_a_raising_check_to_503_rather_than_500() -> None:
    with client(raising("driver exploded")) as http:
        response = http.get(READYZ_ENDPOINT)

    assert response.status_code == 503
    assert response.json()["checks"]["check_0"]["ok"] is False
    assert "driver exploded" in response.json()["checks"]["check_0"]["detail"]


def test_readiness_with_no_checks_is_ready() -> None:
    with client() as http:
        response = http.get(READYZ_ENDPOINT)

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {}}


@pytest.mark.parametrize("retry_after_seconds", [1, 30])
def test_retry_after_is_injectable(retry_after_seconds: int) -> None:
    with client(failing("postgres", "down"), retry_after_seconds=retry_after_seconds) as http:
        response = http.get(READYZ_ENDPOINT)

    assert response.headers["Retry-After"] == str(retry_after_seconds)
