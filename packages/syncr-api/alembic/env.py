"""Alembic environment: async, driven by syncr settings.

The migration engine reuses :func:`syncr_api.core.db.create_db_engine` and reads the
URL from :class:`~syncr_api.core.settings.EnvSettings`, so migrations, the
application, and the tests share one source of truth for the connection string.

``target_metadata`` is the shared declarative ``Base.metadata``. Each feature
module's model module is imported below for the side effect of attaching its tables
to that metadata, so ``--autogenerate`` diffs the real schema.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic import context

import syncr_api.accounts.models as _accounts  # noqa: F401 - registers its tables
import syncr_api.anchors.models as _anchors  # noqa: F401 - registers its tables
import syncr_api.areas.models as _areas  # noqa: F401 - registers its tables
import syncr_api.calendars.models as _calendars  # noqa: F401 - registers its tables
import syncr_api.google_account.models as _google_account  # noqa: F401 - registers its tables
import syncr_api.habits.models as _habits  # noqa: F401 - registers its tables
import syncr_api.idempotency.models as _idempotency  # noqa: F401 - registers its tables
import syncr_api.learned.models as _learned  # noqa: F401 - registers its tables
import syncr_api.oauth.models as _oauth  # noqa: F401 - registers its tables
import syncr_api.offplan.models as _offplan  # noqa: F401 - registers its tables
import syncr_api.plans.models as _plans  # noqa: F401 - registers its tables
import syncr_api.preferences.models as _preferences  # noqa: F401 - registers its tables
import syncr_api.promotions.models as _promotions  # noqa: F401 - registers its tables
import syncr_api.routines.models as _routines  # noqa: F401 - registers its tables
import syncr_api.solving.models as _solving  # noqa: F401 - registers its tables
import syncr_api.tasks.models as _tasks  # noqa: F401 - registers its tables
import syncr_api.templates.models as _templates  # noqa: F401 - registers its tables
import syncr_api.user_settings.models as _user_settings  # noqa: F401 - registers its tables
from syncr_api.core.db import create_db_engine
from syncr_api.core.orm import Base
from syncr_api.core.settings import EnvSettings

# Import every feature module's models here as slices land, so their tables attach
# to Base.metadata. Each such import exists for its registration side effect only,
# so it carries a lint suppression for the unused-import rule.

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return EnvSettings().database_url


def run_migrations_offline() -> None:
    """Emit SQL without a live connection (``alembic upgrade --sql``)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live async connection."""
    engine = create_db_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
