"""Shared fixtures for the api suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from syncr_api.core.app_factory import create_app
from syncr_api.core.settings import EnvSettings, ServiceSettings, build_service_settings
from syncr_common.health import CheckResult, ReadinessCheck
from syncr_common.logging import clear_context, configure_logging, get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

TEST_SERVICE = "syncr-api-test"

# A closed port, so a connection attempt fails fast and for one obvious reason.
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://syncr:syncr@127.0.0.1:1/syncr"


@pytest.fixture(autouse=True)
def _configure_logging() -> None:
    """Configure logging before every test, as an entrypoint does.

    ``create_app`` deliberately does not, so a suite that never asserts on a log line
    would otherwise run against structlog's defaults. ``test`` also turns on the strict
    event-name check, which ``test_the_suite_enforces_the_strict_event_name_check``
    gates rather than assumes.

    Function-scoped, not session-scoped. Logging configuration is process-global, so a
    session-scoped fixture lets one test that reconfigures it silently disable the
    strict check for every module collected after it: alphabetically, that was
    everything from ``test_errors.py`` onward. Reconfiguring per test makes the leak
    impossible rather than something a later wave has to remember.
    """
    configure_logging(environment="test", log_level="info")


@pytest.fixture(autouse=True)
def _fail_if_logging_configuration_leaks() -> Iterator[None]:
    """Fail the test that reconfigures logging and does not hand it back.

    The per-test setup above makes a leak harmless for the NEXT test. This makes it
    visible in the test that CAUSED it, so the suite cannot quietly stop enforcing the
    strict event-name check the way it did when the setup was session-scoped. Under
    ``test`` the malformed name raises before anything renders, so nothing is emitted.
    """
    yield
    try:
        get_logger(TEST_SERVICE).info("logging configuration leaked out of this test")
    except ValueError:
        return
    pytest.fail(
        "this test reconfigured logging and did not restore it, so the strict "
        "event-name check would be off for every test after it. Restore it on teardown; "
        "see the production_log_stream fixture in tests/test_correlation.py."
    )


@pytest.fixture(autouse=True)
def _clean_log_context() -> Iterator[None]:
    """A reused context must not carry a correlation id between tests."""
    clear_context()
    yield
    clear_context()


@pytest.fixture
def settings() -> ServiceSettings:
    """Settings built from defaults only, so a developer's .env cannot change a test."""
    return build_service_settings(service=TEST_SERVICE, env=EnvSettings(_env_file=None))


def passing_check(name: str) -> ReadinessCheck:
    async def check() -> CheckResult:
        return CheckResult(name=name, ok=True)

    return check


def failing_check(name: str, detail: str) -> ReadinessCheck:
    async def check() -> CheckResult:
        return CheckResult(name=name, ok=False, detail=detail)

    return check


@pytest.fixture
def app(settings: ServiceSettings) -> FastAPI:
    """An app with both readiness checks passing and no feature routers."""
    return create_app(
        settings,
        readiness_checks=(passing_check("postgres"), passing_check("migrations")),
    )


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # raise_server_exceptions=False so the catch-all handler's response is what the
    # test sees, which is what a real client gets.
    with TestClient(app, raise_server_exceptions=False) as http:
        yield http


def database_url() -> str:
    """The Postgres URL the integration tests use.

    Read through settings rather than from the environment directly, so the default
    has exactly one definition and ``DATABASE_URL`` overrides it the same way it does
    for the running process.
    """
    return EnvSettings().database_url
