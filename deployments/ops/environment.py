"""What the environment has to carry, read once and refused loudly when it does not.

A secret that is ABSENT is the failure mode this module is written for, not one that is wrong. An
absent variable in a shell script becomes an empty string, and an empty string reaches ``pg_dump``
as a default, ``rclone`` as a path, and ``gpg`` as no recipient at all: the run then succeeds and
produces something useless, which is the one outcome a backup path must never have.

Postgres credentials are deliberately NOT read here. ``libpq`` reads ``PGHOST``, ``PGUSER``,
``PGPASSWORD`` and ``PGDATABASE`` from the environment itself, so the password never passes through
this code, appears in no argument list, and cannot be logged by anything here. What this module does
is require the three non-secret ones to be present, so a misconfigured container fails before it
writes anything rather than dumping the wrong database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from ops.config import (
    DUMP_PREFIX,
    SCRATCH_DIR,
    STAGING_DIR,
    TEXTFILE_DIR,
    WAL_PREFIX,
    WAL_RESTORE_DIR,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

REMOTE_VAR: Final = "SYNCR_BACKUP_REMOTE"
PUBLIC_KEY_VAR: Final = "SYNCR_BACKUP_PUBLIC_KEY"
PRIVATE_KEY_VAR: Final = "SYNCR_BACKUP_PRIVATE_KEY"
STARTED_AT_VAR: Final = "SYNCR_DRILL_STARTED_AT"

# The live database, named so the restore can refuse to write to it. See `ops.restore`.
LIVE_HOST_VAR: Final = "SYNCR_LIVE_PGHOST"
LIVE_PORT_VAR: Final = "SYNCR_LIVE_PGPORT"
LIVE_DATABASE_VAR: Final = "SYNCR_LIVE_PGDATABASE"

# libpq's own variables. Required to be present, never read for their value except to say which
# database a step acted on.
REQUIRED_LIBPQ: Final = ("PGHOST", "PGUSER", "PGDATABASE")


class ConfigurationMissing(Exception):
    """A variable this step cannot proceed without is absent or empty."""


@dataclass(frozen=True, slots=True)
class Target:
    """Which database a step is pointed at, for the messages and for the refusals."""

    host: str
    port: str
    database: str

    def __str__(self) -> str:
        return f"{self.host}:{self.port}/{self.database}"


@dataclass(frozen=True, slots=True)
class Paths:
    """Where the files a step reads and writes live inside the container."""

    staging: Path
    scratch: Path
    textfile: Path
    wal_restore: Path


def required(name: str, environ: Mapping[str, str]) -> str:
    """One variable's value, or a refusal naming it."""
    value = environ.get(name, "").strip()
    if not value:
        raise ConfigurationMissing(
            f"{name} is not set. This step writes nothing rather than guessing: an empty value "
            "reaches the tool it is passed to as a default, which is how a backup succeeds and "
            "produces nothing."
        )
    return value


def libpq_present(environ: Mapping[str, str]) -> Target:
    """Confirm the connection variables are there, and say which database they name."""
    for name in REQUIRED_LIBPQ:
        required(name, environ)
    return Target(
        host=environ["PGHOST"],
        port=environ.get("PGPORT", "5432"),
        database=environ["PGDATABASE"],
    )


def live_target(environ: Mapping[str, str]) -> Target:
    """The live database, which a restore must refuse to write to.

    Required rather than optional, and that is the point: a drill that does not know what the
    production database is cannot refuse to restore onto it, and "restored into the database it was
    dumped from" is a drill that passes while proving nothing.
    """
    return Target(
        host=required(LIVE_HOST_VAR, environ),
        port=environ.get(LIVE_PORT_VAR, "5432"),
        database=required(LIVE_DATABASE_VAR, environ),
    )


def remote_location(environ: Mapping[str, str]) -> str:
    """The rclone remote every object goes to and comes from."""
    return required(REMOTE_VAR, environ)


def paths(environ: Mapping[str, str] | None = None) -> Paths:
    """The four directories, overridable so a test drives real files in a temporary tree."""
    settings = environ if environ is not None else os.environ
    return Paths(
        staging=Path(settings.get("SYNCR_STAGING_DIR", STAGING_DIR)),
        scratch=Path(settings.get("SYNCR_SCRATCH_DIR", SCRATCH_DIR)),
        textfile=Path(settings.get("SYNCR_TEXTFILE_DIR", TEXTFILE_DIR)),
        wal_restore=Path(settings.get("SYNCR_WAL_RESTORE_DIR", WAL_RESTORE_DIR)),
    )


def dump_prefix(environ: Mapping[str, str] | None = None) -> str:
    """Where dumps live under the remote. Overridable so a drill cannot read a live prefix."""
    settings = environ if environ is not None else os.environ
    return settings.get("SYNCR_DUMP_PREFIX", DUMP_PREFIX)


def wal_prefix(environ: Mapping[str, str] | None = None) -> str:
    """Where WAL segments live under the remote."""
    settings = environ if environ is not None else os.environ
    return settings.get("SYNCR_WAL_PREFIX", WAL_PREFIX)
