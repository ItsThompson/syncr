"""The ``just bootstrap-user`` command: create the first tenant and user.

Run against a database, not against the running api, because there is no route that
creates an account: P0 has no sign-up, so this is the only way the first credential
comes into existence. ``docs/runbooks/bootstrap-first-user.md`` is the procedure.

The password is read from a prompt or from the environment, never from the command
line. An argument would be in the shell history, in the process table while it runs,
and in any log that records the command.

Exit codes: 0 when the account exists afterwards, whether this run created it or found
it; 1 when the input was refused or the database could not be reached. Re-running is
therefore safe, which matters for a command whose failure mode during a first
deployment is an operator running it twice.
"""

from __future__ import annotations

import asyncio
import os
import sys
from getpass import getpass

from sqlalchemy.exc import SQLAlchemyError

from syncr_api.accounts.provisioning import AccountProvisioner, BootstrapRejected
from syncr_api.accounts.repository import UserRepository
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database
from syncr_api.core.settings import EnvSettings
from syncr_api.learned.repository import WeightSetRepository
from syncr_common.logging import configure_logging

EMAIL_ENV_VAR = "SYNCR_BOOTSTRAP_EMAIL"
PASSWORD_ENV_VAR = "SYNCR_BOOTSTRAP_PASSWORD"  # noqa: S105 # pragma: allowlist secret

EXIT_OK = 0
EXIT_REJECTED = 1


def main() -> None:
    """Entry point for the ``syncr-bootstrap-user`` console script."""
    settings = EnvSettings()
    # An entrypoint owns the process-global logging setup, as the api and the worker
    # do. Without it a logger obtained at import renders through structlog's console
    # default, so this command's one line would not match the format the rest of a
    # deploy log is in.
    configure_logging(environment=settings.environment, log_level=settings.log_level)
    sys.exit(asyncio.run(run(settings)))


async def run(settings: EnvSettings) -> int:
    """Read the credentials, provision the account, and report what happened."""
    email = os.environ.get(EMAIL_ENV_VAR, "").strip() or _prompt("Email: ")
    password = os.environ.get(PASSWORD_ENV_VAR, "") or getpass("Password: ")
    if not email or not password:
        print("an email and a password are both required", file=sys.stderr)
        return EXIT_REJECTED

    database = create_database(settings.database_url)
    try:
        async with database.sessionmaker() as session, session.begin():
            provisioner = AccountProvisioner(
                users=UserRepository(session),
                clock=utc_now,
                weight_sets=lambda tenant_id: WeightSetRepository(session, tenant_id),
            )
            account = await provisioner.provision(email, password)
    except BootstrapRejected as rejected:
        print(f"refused: {rejected}", file=sys.stderr)
        return EXIT_REJECTED
    except (SQLAlchemyError, OSError) as unreachable:
        # An operator running this against the wrong DATABASE_URL needs the URL and
        # the driver's reason, not a traceback through the async machinery.
        print(f"the database could not be reached: {unreachable}", file=sys.stderr)
        print("check DATABASE_URL and that migrations have been applied", file=sys.stderr)
        return EXIT_REJECTED
    finally:
        await database.engine.dispose()

    if account.created:
        print(f"created tenant {account.tenant_id} with user {account.user_id} <{account.email}>")
    else:
        print(
            f"nothing to do: tenant {account.tenant_id} already holds "
            f"user {account.user_id} <{account.email}>"
        )
    print("verify it by signing in: POST /auth/login with that email and password")
    return EXIT_OK


def _prompt(label: str) -> str:
    """Read one line, or nothing when there is no terminal to read from."""
    if not sys.stdin.isatty():
        return ""
    return input(label).strip()
