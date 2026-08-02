"""Async persistence: the engine, the session factory, and the session dependency.

The pool is bounded and small on purpose. There is no connection pooler in front
of Postgres: a pooler in transaction mode reintroduces the asyncpg
prepared-statement hazard, which is one of the reasons a managed database was
rejected, so adding one here would reintroduce the problem that decision avoided.

Connecting is lazy, so building an app does not require a reachable database.
``GET /readyz`` is what surfaces connectivity, via :func:`db_readiness_check`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# `get_session` is a FastAPI dependency, not a decorated route handler, so the
# runtime-evaluated-decorators config does not cover it. FastAPI resolves each
# parameter annotation at runtime to build the dependency, so `Request` must stay
# importable at runtime or FastAPI treats `request` as a validated query field.
from starlette.requests import Request  # noqa: TC002

from syncr_common.health import CheckResult
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI
    from starlette.types import Lifespan

    from syncr_common.health import ReadinessCheck

# Postgres runs with max_connections 50 and there is no pooler, so the api's two
# uvicorn workers and the worker process each stay well inside that ceiling.
# `pool_pre_ping` discards connections severed by a Postgres restart or an idle
# timeout before they are handed to a request.
POOL_SIZE = 5
MAX_OVERFLOW = 5
POOL_TIMEOUT_SECONDS = 30

DB_CHECK_NAME = "postgres"
# What an unreachable database reports on the wire. The driver's own message names
# the host, the port, the executed SQL, and the credentials' user, and a deploy gate
# is often the most widely reachable endpoint a stack has. The detail goes to the log,
# where it is needed; the wire gets a stable reason.
DB_UNREACHABLE_REASON = "unreachable"

_log = get_logger("syncr.db")


def create_db_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Build the async engine backed by a bounded connection pool."""
    return create_async_engine(
        database_url,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=POOL_TIMEOUT_SECONDS,
        pool_pre_ping=True,
        echo=echo,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build the session factory.

    ``expire_on_commit=False`` keeps ORM objects usable after the request's commit,
    because they are serialized post-commit.
    """
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@dataclass(frozen=True)
class Database:
    """The engine and session-factory pair carried on ``app.state.db``."""

    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]


def create_database(database_url: str) -> Database:
    """Compose the engine and session factory for one process."""
    engine = create_db_engine(database_url)
    return Database(engine=engine, sessionmaker=create_sessionmaker(engine))


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped :class:`AsyncSession`.

    The session factory is read from ``app.state.db``, attached at wiring time, so
    this dependency holds no module-global state and is substitutable in tests.
    """
    database: Database = request.app.state.db
    async with database.sessionmaker() as session:
        yield session


def create_db_lifespan(engine: AsyncEngine) -> Lifespan[FastAPI]:
    """Lifespan that disposes the connection pool on shutdown."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    return lifespan


def db_readiness_check(engine: AsyncEngine) -> ReadinessCheck:
    """Readiness check that confirms Postgres is reachable.

    Never raises: a connectivity failure resolves to a failed
    :class:`~syncr_common.health.CheckResult`, so ``/readyz`` answers 503 rather
    than 500. The driver's message is logged rather than returned, so the endpoint
    discloses no topology.
    """

    async def check() -> CheckResult:
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - any driver error is "not ready"
            _log.warning("db.readiness.failed", error=str(exc))
            return CheckResult(name=DB_CHECK_NAME, ok=False, detail=DB_UNREACHABLE_REASON)
        return CheckResult(name=DB_CHECK_NAME, ok=True)

    return check
