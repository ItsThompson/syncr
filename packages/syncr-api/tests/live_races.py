"""The harness two race modules share: a held window, a wired client, and an index read by rule.

A race test needs three things that are the same wherever the race is: a window between a read and
the write it decided on, held open until the racing request has committed; a client over the real
app that renders a fault as the response a caller receives rather than raising it into the test; and
a way to name the unique index a rule leans on without spelling the name.

None of that is specific to which rule is being raced. What IS specific is the seam: which read is
made to wait, and what the two callers are then answered. That stays in the module driving the race.

:func:`the_unique_index_over` reads the name off the table's own declaration rather than taking a
constant, so a test describes the guarantee (these columns are unique together) rather than a name,
and a constant repointed at another index cannot make it agree.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import TYPE_CHECKING

import httpx

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from tests.control_models import table_of
from tests.live_tenants import PASSWORD

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.orm import DeclarativeBase

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings

# The origin a browser sends, which the app's CORS rules accept.
BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]


class Window:
    """The gap between a read and the write it guards, held open on demand.

    ``hold_for`` bounds the wait, so a window nobody closes fails the test rather than hanging the
    suite. Each module states its own budget: it has to outlast the racing request's whole round
    trip, and how long that is depends on what the racing request does.

    ``reads`` counts the reads that passed through the window. A module that answers a refusal by
    running its courtesy read again tells the two candidate answers apart by that count; a module
    whose seam only has to fire once reads it to decide whether it has already fired.
    """

    def __init__(self, *, hold_for: float) -> None:
        self.open = asyncio.Event()
        self.closed = asyncio.Event()
        self.reads = 0
        self._hold_for = hold_for

    async def hold(self) -> None:
        self.reads += 1
        self.open.set()
        await asyncio.wait_for(self.closed.wait(), timeout=self._hold_for)


@asynccontextmanager
async def wired_app(
    live_database_url: str, settings: ServiceSettings
) -> AsyncIterator[httpx.AsyncClient]:
    """A client over the real app: real dependencies, real transaction, real handler map.

    ``raise_app_exceptions=False`` so a fault renders as the response a caller receives rather
    than as an exception in the test, which is the difference a race module is about.
    """
    database = create_database(live_database_url)
    app = create_app(settings)
    app.state.db = database
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    await database.engine.dispose()


async def signed_in(client: httpx.AsyncClient, owner: UserRecord) -> dict[str, str]:
    """The headers a signed-in browser sends. The cookie is read off the header, not a jar.

    The session cookie is ``Secure`` and a client that honors that will not send it back over
    ``http://testserver``.
    """
    answered = await client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": owner.email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


def the_unique_index_over(table: type[DeclarativeBase], columns: tuple[str, ...]) -> str:
    """The name of the one unique index this table declares over exactly ``columns``, in order."""
    named = [
        str(index.name)
        for index in table_of(table).indexes
        if index.unique and tuple(column.name for column in index.columns) == columns
    ]
    assert len(named) == 1, f"{table.__name__} declares {named} over {columns}"
    return named[0]
