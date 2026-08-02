"""The RFC 9457 problem-details contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from syncr_api.core.app_factory import create_app
from syncr_api.core.correlation import CORRELATION_ID_HEADER
from syncr_api.core.errors import (
    PROBLEM_JSON_MEDIA_TYPE,
    Conflict,
    DependencyUnavailable,
    FieldError,
    Forbidden,
    MalformedRequest,
    NotFound,
    RateLimited,
    SyncrError,
    Unauthorized,
    ValidationFailed,
)

if TYPE_CHECKING:
    from syncr_api.core.settings import ServiceSettings

RAISE_PATH = "/raise"
BODY_PATH = "/body"

DOMAIN_ERRORS = (
    (MalformedRequest, 400, "syncr:malformed-request"),
    (Unauthorized, 401, "syncr:unauthorized"),
    (Forbidden, 403, "syncr:forbidden"),
    (NotFound, 404, "syncr:not-found"),
    (Conflict, 409, "syncr:conflict"),
    (ValidationFailed, 422, "syncr:validation-failed"),
    (RateLimited, 429, "syncr:rate-limited"),
    (DependencyUnavailable, 503, "syncr:dependency-unavailable"),
)


class PinRequest(BaseModel):
    block_id: str
    start_minute: int


def build_raising_app(settings: ServiceSettings, exc: Exception) -> FastAPI:
    router = APIRouter()

    @router.get(RAISE_PATH)
    async def raise_it() -> None:
        raise exc

    @router.post(BODY_PATH)
    async def accept_body(_body: PinRequest) -> dict[str, str]:
        return {"status": "ok"}

    return create_app(settings, feature_routers=(lambda: router,))


def client_for(settings: ServiceSettings, exc: Exception) -> TestClient:
    return TestClient(build_raising_app(settings, exc), raise_server_exceptions=False)


@pytest.mark.parametrize(("error", "status", "problem_type"), DOMAIN_ERRORS)
def test_every_domain_error_maps_to_a_problem_response(
    settings: ServiceSettings,
    error: type[SyncrError],
    status: int,
    problem_type: str,
) -> None:
    detail = "The week is unchanged. Reading the plan still works."

    with client_for(settings, error(detail)) as http:
        response = http.get(RAISE_PATH)

    assert response.status_code == status
    assert response.headers["content-type"] == PROBLEM_JSON_MEDIA_TYPE
    body = response.json()
    assert body["type"] == problem_type
    assert body["status"] == status
    assert body["detail"] == detail
    assert body["title"]


def test_a_problem_omits_the_optional_members_it_does_not_carry(
    settings: ServiceSettings,
) -> None:
    with client_for(settings, NotFound("No plan revision for 2026-W07.")) as http:
        body = http.get(RAISE_PATH).json()

    assert "errors" not in body
    assert set(body) == {"type", "title", "status", "detail", "instance"}


def test_instance_carries_the_correlation_id(settings: ServiceSettings) -> None:
    with client_for(settings, Conflict("A proposal already exists for 2026-W07.")) as http:
        response = http.get(RAISE_PATH, headers={CORRELATION_ID_HEADER: "corr-abc"})

    assert response.json()["instance"] == "corr-abc"
    assert response.headers[CORRELATION_ID_HEADER] == "corr-abc"


def test_a_validation_error_carries_field_level_errors(settings: ServiceSettings) -> None:
    raised = ValidationFailed(
        "The minimum chunk exceeds the estimate. The task is unchanged.",
        errors=[FieldError(field="minimum_chunk_minutes", message="must not exceed the estimate")],
    )

    with client_for(settings, raised) as http:
        body = http.get(RAISE_PATH).json()

    assert body["errors"] == [
        {"field": "minimum_chunk_minutes", "message": "must not exceed the estimate"}
    ]


def test_a_503_carries_retry_after(settings: ServiceSettings) -> None:
    with client_for(settings, DependencyUnavailable("Google is unreachable.")) as http:
        response = http.get(RAISE_PATH)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"


def test_a_429_carries_retry_after(settings: ServiceSettings) -> None:
    with client_for(settings, RateLimited("Too many solves requested.")) as http:
        response = http.get(RAISE_PATH)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"


def test_a_404_carries_no_retry_after(settings: ServiceSettings) -> None:
    with client_for(settings, NotFound("No such area.")) as http:
        response = http.get(RAISE_PATH)

    assert "Retry-After" not in response.headers


def test_request_validation_uses_the_same_problem_shape(settings: ServiceSettings) -> None:
    with client_for(settings, NotFound("unused")) as http:
        response = http.post(BODY_PATH, json={"block_id": "b-1"})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_JSON_MEDIA_TYPE
    body = response.json()
    assert body["type"] == "syncr:validation-failed"
    assert body["errors"] == [{"field": "body.start_minute", "message": "Field required"}]
    assert body["instance"]


def test_an_unhandled_exception_renders_a_generic_500(settings: ServiceSettings) -> None:
    with client_for(settings, RuntimeError("asyncpg exploded with the password in it")) as http:
        response = http.get(RAISE_PATH)

    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM_JSON_MEDIA_TYPE
    body = response.json()
    assert body["type"] == "syncr:internal-error"
    assert body["detail"] == "An unexpected error occurred. The request was not applied."
    assert "asyncpg" not in response.text
    assert body["instance"]
