"""The settings, the engine and the session factory a one-shot container builds and then disposes.

The pool is TWO connections, not the api's ten. A one-shot job runs one tenant at a time and never
serves a request, so a wider pool would hold connections against a Postgres with ``max_connections``
at 50 and no pooler in front of it, for no concurrency it has.

``pool_pre_ping`` is on for the same reason it is on in the api: the container starts at 03:00,
which is when the backup runs, and a connection severed by a Postgres restart must be discarded
before a
statement is handed to it rather than failing a tenant's night.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from syncr_common.config import SyncrSettings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

POOL_SIZE: Final = 2
MAX_OVERFLOW: Final = 0
POOL_TIMEOUT_SECONDS: Final = 10


class LearningSettings(SyncrSettings):
    """What the nightly job reads from the environment."""

    service: str = "syncr-learning"
    # The same local default the api's settings carry, and for the same reason: both read one
    # sectioned root `.env`, and a second default would let the job and the api disagree about which
    # database is being talked about on a developer's machine. Compose injects the in-network form.
    database_url: str = (
        "postgresql+asyncpg://syncr:syncr@localhost:5432/syncr"  # pragma: allowlist secret
    )
    # Where to write the run's metric exposition. Empty means this deployment does not collect it,
    # and empty is the default because a one-shot cannot be scraped: a scrape would arrive after it
    # exited. The node exporter's textfile collector reads a directory, and Compose supplies it.
    textfile_collector_dir: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Database:
    """The engine and the factory, held together so the entrypoint disposes what it built."""

    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]


def create_database(database_url: str) -> Database:
    """The engine and session factory for one run.

    ``expire_on_commit=False`` so a value read out of a session stays usable after it closes, and
    ``autoflush=False`` because nothing here mutates a mapped object: every write is one explicit
    insert.
    """
    engine = create_async_engine(
        database_url,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=POOL_TIMEOUT_SECONDS,
        pool_pre_ping=True,
    )
    return Database(
        engine=engine,
        sessions=async_sessionmaker(engine, expire_on_commit=False, autoflush=False),
    )
