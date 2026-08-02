"""Redaction, event-name, and correlation-id behavior of the real logging chain.

Every assertion runs against the rendered JSON line rather than a captured
intermediate, so the processor order that makes redaction unskippable is part of
what is under test.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import structlog

from syncr_common.logging import (
    REDACTED,
    bind_correlation_id,
    bind_tenant_id,
    clear_context,
    configure_logging,
    current_correlation_id,
    get_logger,
    is_sensitive_key,
    new_correlation_id,
)

BLOCK_TITLE = "Kontron Placement Interview"
ANCHOR_LOCATION = "Kontron AG, Augsburg"
LEAKED_VALUE = "s3cr3t-value"

LEVELS = ("debug", "info", "warning", "error", "critical")

SECRET_KEYS = (
    "password",
    "db_passwd",
    "session_secret",
    "refresh_token",
    "access_token",
    "client_secret",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "private_key",
    "google_credential",
    "request_signature",
    "bearer",
)

# Emit one event at the given level and return the rendered line, parsed.
Emit = Callable[..., dict[str, Any]]


@pytest.fixture
def emit() -> Iterator[Emit]:
    """Emit through the real chain, one line at a time.

    Configured at ``debug`` so a call at any level passes the level filter, and in
    ``production`` so the strict event-name check cannot mask a redaction test.
    """
    stream = io.StringIO()
    configure_logging(environment="production", log_level="debug", stream=stream)
    clear_context()

    def emit_one(level: str, event: str, **fields: object) -> dict[str, Any]:
        stream.seek(0)
        stream.truncate()
        getattr(get_logger("syncr-test"), level)(event, **fields)
        lines = [line for line in stream.getvalue().splitlines() if line]
        assert len(lines) == 1, f"expected one line per event, got {len(lines)}"
        parsed: dict[str, Any] = json.loads(lines[0])
        return parsed

    yield emit_one
    clear_context()


@pytest.mark.parametrize("level", LEVELS)
def test_block_title_never_reaches_the_line(emit: Emit, level: str) -> None:
    line = emit(level, "plan.block.placed", block_id="b-1", title=BLOCK_TITLE)

    assert line["title"] == REDACTED
    assert BLOCK_TITLE not in json.dumps(line)
    assert line["block_id"] == "b-1"


@pytest.mark.parametrize("level", LEVELS)
def test_location_never_reaches_the_line(emit: Emit, level: str) -> None:
    line = emit(level, "calendar.anchor.read", location=ANCHOR_LOCATION)

    assert line["location"] == REDACTED
    assert ANCHOR_LOCATION not in json.dumps(line)


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("key", SECRET_KEYS)
def test_secret_keys_never_reach_the_line(emit: Emit, level: str, key: str) -> None:
    line = emit(level, "auth.token.issued", **{key: LEAKED_VALUE})

    assert line[key] == REDACTED
    assert LEAKED_VALUE not in json.dumps(line)


def test_prefixed_content_keys_are_redacted(emit: Emit) -> None:
    line = emit(
        "info",
        "calendar.anchor.matched",
        anchor_title=BLOCK_TITLE,
        anchor_location=ANCHOR_LOCATION,
        anchor_id="a-9",
    )

    assert line["anchor_title"] == REDACTED
    assert line["anchor_location"] == REDACTED
    assert line["anchor_id"] == "a-9"


def test_nested_content_is_redacted(emit: Emit) -> None:
    line = emit(
        "info",
        "plan.revision.appended",
        blocks=[{"block_id": "b-1", "title": BLOCK_TITLE}],
        diff={"changed": {"title": BLOCK_TITLE}},
    )

    assert BLOCK_TITLE not in json.dumps(line)
    assert line["blocks"][0]["block_id"] == "b-1"


def test_context_bound_secrets_are_redacted(emit: Emit) -> None:
    structlog.contextvars.bind_contextvars(session_token=LEAKED_VALUE)

    line = emit("info", "http.request.completed")

    assert line["session_token"] == REDACTED
    assert LEAKED_VALUE not in json.dumps(line)


def test_identifier_fields_survive(emit: Emit) -> None:
    line = emit(
        "info",
        "solve.completed",
        iso_week="2026-W07",
        operation_id="op-1",
        input_version=47,
        duration_ms=1284,
        blocks_placed=91,
        verdict_feasible=False,
    )

    assert line["iso_week"] == "2026-W07"
    assert line["operation_id"] == "op-1"
    assert line["input_version"] == 47
    assert line["blocks_placed"] == 91
    assert line["verdict_feasible"] is False


def test_every_line_carries_the_correlation_and_tenant_id(emit: Emit) -> None:
    correlation_id = new_correlation_id()
    bind_correlation_id(correlation_id)
    bind_tenant_id("tenant-7")

    first = emit("info", "solve.requested")
    second = emit("debug", "solve.inputs.assembled")

    assert first["correlation_id"] == correlation_id
    assert second["correlation_id"] == correlation_id
    assert first["tenant_id"] == "tenant-7"
    assert current_correlation_id() == correlation_id


def test_clearing_the_context_drops_the_correlation_id(emit: Emit) -> None:
    bind_correlation_id("corr-1")
    clear_context()

    assert current_correlation_id() is None
    assert "correlation_id" not in emit("info", "worker.tick.started")


def test_line_carries_level_timestamp_and_service(emit: Emit) -> None:
    line = emit("warning", "calendar.source.stale", source_id="s-1")

    assert line["level"] == "warning"
    assert line["service"] == "syncr-test"
    assert line["event"] == "calendar.source.stale"
    assert line["timestamp"]


def test_a_logger_obtained_before_configuration_still_renders_json() -> None:
    # A module-level `get_logger(...)` runs at import, before configure_logging. If
    # the service field were bound eagerly, structlog's default console renderer
    # would be frozen into every line that logger ever emits.
    logger = get_logger("syncr-early")
    stream = io.StringIO()
    configure_logging(environment="production", log_level="info", stream=stream)

    logger.info("worker.loop.started", runners=0)

    line = json.loads(stream.getvalue())
    assert line["service"] == "syncr-early"
    assert line["event"] == "worker.loop.started"
    assert line["runners"] == 0


def test_free_text_event_name_raises_in_development() -> None:
    configure_logging(environment="development", log_level="debug", stream=io.StringIO())

    with pytest.raises(ValueError, match="dotted stable name"):
        get_logger("syncr-test").info("solve finished successfully")


def test_free_text_event_name_passes_through_in_production() -> None:
    stream = io.StringIO()
    configure_logging(environment="production", log_level="debug", stream=stream)

    get_logger("syncr-test").info("solve finished successfully")

    assert json.loads(stream.getvalue())["event"] == "solve finished successfully"


@pytest.mark.parametrize(
    "key",
    ["title", "location", "block_title", "REFRESH_TOKEN", "Client_Secret"],
)
def test_sensitive_keys_are_recognized_case_insensitively(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize(
    "key",
    ["block_id", "tenant_id", "iso_week", "session_mode_active", "authority_class", "author"],
)
def test_identifier_keys_are_not_treated_as_sensitive(key: str) -> None:
    assert not is_sensitive_key(key)
