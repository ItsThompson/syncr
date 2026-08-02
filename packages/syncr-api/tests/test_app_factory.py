"""The application factory: mounted contract, the router registry, and wiring."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from syncr_api.core.app_factory import FEATURE_ROUTERS, create_app
from syncr_api.core.observability import METRICS_ENDPOINT
from syncr_api.core.settings import API_PREFIX, ServiceSettings
from syncr_common.health import HEALTHZ_ENDPOINT, READYZ_ENDPOINT, RETRY_AFTER_SECONDS
from tests.conftest import failing_check, passing_check


def test_liveness_answers_200_without_checking_a_dependency(
    settings: ServiceSettings,
) -> None:
    app = create_app(settings, readiness_checks=(failing_check("postgres", "refused"),))

    with TestClient(app) as http:
        response = http.get(HEALTHZ_ENDPOINT)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_answers_200_when_the_database_and_the_head_are_good(
    client: TestClient,
) -> None:
    response = client.get(READYZ_ENDPOINT)

    assert response.status_code == 200
    assert response.json()["checks"]["postgres"]["ok"] is True
    assert response.json()["checks"]["migrations"]["ok"] is True


def test_readiness_answers_503_with_retry_after_when_the_head_is_not_applied(
    settings: ServiceSettings,
) -> None:
    app = create_app(
        settings,
        readiness_checks=(
            passing_check("postgres"),
            failing_check("migrations", "head 0001_baseline is not applied"),
        ),
    )

    with TestClient(app) as http:
        response = http.get(READYZ_ENDPOINT)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == str(RETRY_AFTER_SECONDS)
    assert "0001_baseline" in response.json()["checks"]["migrations"]["detail"]


def test_metrics_serves_prometheus_exposition(client: TestClient) -> None:
    response = client.get(METRICS_ENDPOINT)

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "syncr_method_duration_seconds" in response.text


def test_health_and_metrics_stay_out_of_the_openapi_document(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    assert HEALTHZ_ENDPOINT not in paths
    assert READYZ_ENDPOINT not in paths
    assert METRICS_ENDPOINT not in paths


def test_a_registered_feature_router_is_mounted(settings: ServiceSettings) -> None:
    def build_areas_router() -> APIRouter:
        router = APIRouter(prefix=f"{API_PREFIX}/areas", tags=["areas"])

        @router.get("")
        async def list_areas() -> list[str]:
            return ["recovery"]

        return router

    app = create_app(settings, feature_routers=(build_areas_router,))

    with TestClient(app) as http:
        response = http.get(f"{API_PREFIX}/areas")

    assert response.status_code == 200
    assert response.json() == ["recovery"]
    assert f"{API_PREFIX}/areas" in app.openapi()["paths"]


def test_registry_entries_all_build_a_router(settings: ServiceSettings) -> None:
    # The registry is append-only, so this holds for every entry a later slice adds
    # and fails on an entry that is not a zero-argument router factory.
    for build_router in FEATURE_ROUTERS:
        assert isinstance(build_router(), APIRouter)

    assert create_app(settings) is not None


def test_settings_and_logger_are_reachable_on_app_state(app: FastAPI) -> None:
    assert app.state.settings.service == "syncr-api-test"
    assert app.state.log is not None
