"""The ``syncr-drill-seed`` console script: give a restore drill something it can afford to lose.

A drill refuses to report a pass over a database whose evidence tables were empty when the dump was
taken, because an empty table restores perfectly. On a deployed host that evidence is the operator's
real plan history. In development there is none, so this writes some, through the repositories and
the services the product writes it through: the tenant through the bootstrap command a first
deployment runs, the declarations through the services their routes reach, the week through the
horizon maintainer and a solve, and what happened in it through the outcome, pin and concession
paths.

**It writes no SQL and it holds no truncate.** Every write is a service call or a repository call,
so a row it produces satisfies the invariants that path enforces, and a column that moves moves for
this seeder too rather than leaving it writing a shape the product can no longer read.

**It converges rather than accumulating.** Every step reads before it writes and the concession is
an upsert, so a second run against a seeded database writes nothing new and a drill can be repeated.
No reset is needed and none is shipped: nothing here removes a row.

**It refuses a database that is not the drill's own before it writes anything.** The rule, and what
it can and cannot see, are in :mod:`syncr_api.recovery.drill_target`.

Exit codes: 0 when the evidence is in place, whether this run wrote it or found it; 1 when the
target was refused, the bootstrap command failed, or the solve placed nothing to record an outcome
against.
The judgement of what it produced is `python3 -m ops.compare`'s and the fingerprint's, never this
script's: it reports what it did and the drill reports whether that was enough.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Final

from sqlalchemy.exc import SQLAlchemyError

from syncr_api.accounts.bootstrap import EMAIL_ENV_VAR, PASSWORD_ENV_VAR
from syncr_api.accounts.repository import UserRepository
from syncr_api.core.clock import utc_now
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import ALL_SCOPES
from syncr_api.recovery.drill_evidence import write_the_evidence
from syncr_api.recovery.drill_history import NothingWasPlaced
from syncr_api.recovery.drill_target import NotTheDrillsDatabase, require_the_drills_own_database
from syncr_api.worker.main import WorkerContext, build_context
from syncr_common.logging import configure_logging

if TYPE_CHECKING:
    from collections.abc import Callable

    from syncr_api.core.db import Database
    from syncr_api.recovery.drill_evidence import Written

# The address the drill's own tenant is provisioned under. Distinct from every other identity in the
# repository, so the tenant this seeder may write beside is exactly the one it created.
DRILL_EMAIL: Final = "drill-seeder@localhost"

BOOTSTRAP_COMMAND: Final = "syncr-bootstrap-user"

# The password is minted per run and recorded nowhere, so the account it hashes cannot be signed in
# to. Nothing signs in during a drill, and a password this repository carried would be a credential
# in it.
PASSWORD_BYTES: Final = 32

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1

# Runs the bootstrap console script for one address and answers with its exit status.
type Bootstrap = Callable[[str, str], int]


class BootstrapFailed(Exception):
    """The bootstrap console script did not provision the drill's tenant."""


def main() -> None:
    """Entry point for the ``syncr-drill-seed`` console script."""
    context = build_context()
    configure_logging(
        environment=context.settings.environment, log_level=context.settings.log_level
    )
    sys.exit(asyncio.run(run(context)))


async def run(context: WorkerContext, *, bootstrap: Bootstrap | None = None) -> int:
    """Seed the evidence and say what is in place, or say why nothing was written."""
    try:
        written = await seed(context, bootstrap=bootstrap or _through_the_console_script)
    except (NotTheDrillsDatabase, BootstrapFailed, NothingWasPlaced) as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return EXIT_REFUSED
    except (SQLAlchemyError, OSError) as unreachable:
        print(f"the database could not be reached: {unreachable}", file=sys.stderr)
        print("check DATABASE_URL and that migrations have been applied", file=sys.stderr)
        return EXIT_REFUSED
    finally:
        await context.database.engine.dispose()
    _report(written)
    return EXIT_OK


async def seed(context: WorkerContext, *, bootstrap: Bootstrap) -> Written:
    """Refuse a target that is not the drill's own, provision its tenant, then write as it."""
    database: Database = context.database
    async with database.sessionmaker() as session:
        await require_the_drills_own_database(session, drill_email=DRILL_EMAIL)

    status = bootstrap(DRILL_EMAIL, secrets.token_urlsafe(PASSWORD_BYTES))
    if status != 0:
        raise BootstrapFailed(
            f"{BOOTSTRAP_COMMAND} exited {status} rather than provisioning {DRILL_EMAIL}. It "
            "states its own reason above; nothing else has been written"
        )
    return await write_the_evidence(context, await _the_drills_principal(database), now=utc_now())


def _through_the_console_script(email: str, password: str) -> int:
    """Run the command a first deployment runs, in a process of its own.

    The command rather than the provisioner it composes, because that is what a first deployment
    runs and what its idempotence is stated about: re-running it reports the account it found.
    """
    found = shutil.which(BOOTSTRAP_COMMAND)
    if found is None:
        raise BootstrapFailed(
            f"{BOOTSTRAP_COMMAND} is not on PATH, so the drill's tenant cannot be provisioned "
            "through it. This runs in the api image, where both commands are installed together"
        )
    completed = subprocess.run(  # noqa: S603 - a resolved path, and no argument comes from a caller
        [found],
        env={**os.environ, EMAIL_ENV_VAR: email, PASSWORD_ENV_VAR: password},
        check=False,
    )
    return completed.returncode


async def _the_drills_principal(database: Database) -> Principal:
    """The subject every service call is made for, read back from the provisioned row."""
    async with database.sessionmaker() as session:
        user = await UserRepository(session).find_by_email(DRILL_EMAIL)
    if user is None:
        raise BootstrapFailed(
            f"{BOOTSTRAP_COMMAND} reported success and this database holds no {DRILL_EMAIL}, so "
            "the two are not looking at the same database. Check DATABASE_URL"
        )
    return Principal(tenant_id=user.tenant_id, user_id=user.id, scopes=ALL_SCOPES)


def _report(written: Written) -> None:
    print(
        f"{written.iso_week}: {'materialized' if written.materialized else 'already planned'}, "
        f"{'solved' if written.solved else 'already solved'}, "
        f"{'a proposal adopted' if written.adopted else 'no proposal to adopt'}, "
        f"{written.placed} occurrences placed, {written.recorded} outcomes recorded, "
        f"{written.confirmed} days confirmed, "
        f"{'pinned one block' if written.pinned else 'already pinned'}"
    )
    print(
        "the fingerprint is what judges this: `python3 -m ops.compare` states whether the five "
        "evidence tables held rows and whether a rotation cursor had advanced"
    )


if __name__ == "__main__":
    main()
