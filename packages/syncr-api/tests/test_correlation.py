"""Correlation-id acceptance, generation, echoing, and log propagation."""

from __future__ import annotations

import io
import json
import re
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.testclient import TestClient

from syncr_api.core.app_factory import create_app
from syncr_api.core.correlation import (
    CORRELATION_ID_HEADER,
    MAX_CORRELATION_ID_LENGTH,
)
from syncr_common.health import HEALTHZ_ENDPOINT
from syncr_common.logging import configure_logging, current_correlation_id, get_logger

if TYPE_CHECKING:
    from syncr_api.core.settings import ServiceSettings

LOG_PATH = "/logged"
HEX_32 = re.compile(r"^[0-9a-f]{32}$")


def build_logging_app(settings: ServiceSettings) -> APIRouter:
    router = APIRouter()

    @router.get(LOG_PATH)
    async def emit() -> dict[str, str | None]:
        get_logger(settings.service).info("plan.week.read", iso_week="2026-W07")
        return {"correlation_id": current_correlation_id()}

    return router


def test_an_inbound_correlation_id_is_accepted_and_echoed(client: TestClient) -> None:
    response = client.get(HEALTHZ_ENDPOINT, headers={CORRELATION_ID_HEADER: "browser-pin-1"})

    assert response.headers[CORRELATION_ID_HEADER] == "browser-pin-1"


def test_a_correlation_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get(HEALTHZ_ENDPOINT)

    assert HEX_32.fullmatch(response.headers[CORRELATION_ID_HEADER])


def test_a_malformed_inbound_id_is_dropped_and_replaced(client: TestClient) -> None:
    hostile = "x" * (MAX_CORRELATION_ID_LENGTH + 1)

    response = client.get(HEALTHZ_ENDPOINT, headers={CORRELATION_ID_HEADER: hostile})

    assert response.headers[CORRELATION_ID_HEADER] != hostile
    assert HEX_32.fullmatch(response.headers[CORRELATION_ID_HEADER])


def test_an_id_with_illegal_characters_is_dropped_and_replaced(client: TestClient) -> None:
    response = client.get(HEALTHZ_ENDPOINT, headers={CORRELATION_ID_HEADER: "not a valid id"})

    assert HEX_32.fullmatch(response.headers[CORRELATION_ID_HEADER])


def test_two_requests_get_different_generated_ids(client: TestClient) -> None:
    first = client.get(HEALTHZ_ENDPOINT).headers[CORRELATION_ID_HEADER]
    second = client.get(HEALTHZ_ENDPOINT).headers[CORRELATION_ID_HEADER]

    assert first != second


def test_the_handler_sees_the_same_id_the_response_echoes(
    settings: ServiceSettings,
) -> None:
    app = create_app(settings, feature_routers=(lambda: build_logging_app(settings),))

    with TestClient(app) as http:
        response = http.get(LOG_PATH, headers={CORRELATION_ID_HEADER: "one-user-action"})

    assert response.json()["correlation_id"] == "one-user-action"
    assert response.headers[CORRELATION_ID_HEADER] == "one-user-action"


def test_every_log_line_emitted_during_the_request_carries_the_id(
    settings: ServiceSettings,
) -> None:
    app = create_app(settings, feature_routers=(lambda: build_logging_app(settings),))
    stream = io.StringIO()
    configure_logging(environment="production", log_level="info", stream=stream)

    with TestClient(app) as http:
        http.get(LOG_PATH, headers={CORRELATION_ID_HEADER: "traced-1"})

    lines = [json.loads(line) for line in stream.getvalue().splitlines() if line]
    assert lines, "expected the handler's line to be captured"
    assert all(line["correlation_id"] == "traced-1" for line in lines)
