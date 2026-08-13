"""Two replacements of one owner arriving together, and a removal landing inside the window.

A replacement used to read the owner's row and then decide between an insert and an update from
what it read. The read holds no lock, so both decisions could be wrong by the time the write ran,
and they were wrong in two different ways:

**Two replacements racing one owner.** Both read nothing stored, both insert, and the unique index
refuses the second. Nothing maps that refusal, so the loser is answered 500 for a request nothing
was wrong with and its declaration is lost.

**A removal landing between the read and the write.** The replacement read a row, so it issued an
``UPDATE``, and the row was gone by the time that ran: the statement matched nothing, and the
caller was answered 200 carrying ``declared: null`` for a declaration that was never stored.

One statement closes both, so both are driven here rather than one being assumed from the other.
A single serial pass is evidence of neither: the interleaving is stated by a seam that holds the
window between the read and the write open until the racing request has committed.

The three unique indexes are still the guarantee, and are asserted twice over: the migrated schema
carries one per owner reference, and a second row hand-written for one owner is refused by the
index that owner's kind is constrained by. That is the index the replacement now names as its
conflict target, so a target pointed at the wrong one would leave a kind of owner writing two rows.

The window, the wired client and the index lookup are ``tests/live_races.py``'s, because none of
them is specific to which rule is raced. What is specific and stays here is the seam: which read is
made to wait, and what the two callers are then answered.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time
from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.races import refused_index
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.habits.config import HABITS_PREFIX
from syncr_api.preferences.models import PreferenceRow
from syncr_api.preferences.repository import OWNER_COLUMN, PreferenceRepository
from syncr_api.tasks.config import TASKS_PREFIX
from syncr_domain.preferences import (
    LocalTimeWindow,
    Preference,
    PreferenceOwner,
    PreferenceOwnerKind,
    PreferenceStrength,
)
from tests.live_races import Window, signed_in, the_unique_index_over, wired_app
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import httpx
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_api.preferences.records import PreferenceRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

# Long enough that the racing request's commit lands inside the window, short enough that a window
# nobody closes fails the test rather than hanging the suite.
WINDOW_SECONDS = 10

# How long a replacement blocked on an uncommitted one is given to prove it is still blocked. The
# assertion is that it has NOT finished, so a slower box waits longer and cannot turn it green.
BLOCKED_SECONDS = 1.0

EARLY = {"start": "05:30", "end": "07:00"}
EVENING = {"start": "19:00", "end": "21:00"}

# Two declarations no stored row and no response body could confuse, named by the order they reach
# the table rather than by the order the requests start in.
WRITTEN_FIRST = {"windows": [EARLY], "strength": "strong"}
WRITTEN_SECOND = {"windows": [EVENING], "strength": "soft"}

STORED_FIRST = [{"start": "05:30:00", "end": "07:00:00"}]
STORED_SECOND = [{"start": "19:00:00", "end": "21:00:00"}]

# The same two declarations as entities, for the pair of writes driven over two connections of
# this test's own rather than over two requests.
WINDOW_WRITTEN_FIRST = LocalTimeWindow(start=time(5, 30), end=time(7, 0))
WINDOW_WRITTEN_SECOND = LocalTimeWindow(start=time(19, 0), end=time(21, 0))


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    live = create_db_engine(live_database_url)
    yield live
    await live.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


@pytest.fixture
async def wired(
    live_database_url: str, settings: ServiceSettings
) -> AsyncIterator[httpx.AsyncClient]:
    async with wired_app(live_database_url, settings) as client:
        yield client


class Owned:
    """One Area with a habit and a task inside it, each addressable by its preference path."""

    def __init__(self, *, area_id: str, habit_id: str, task_id: str) -> None:
        self._by_kind = {
            PreferenceOwnerKind.AREA: (area_id, f"{AREAS_PREFIX}/{area_id}/preference"),
            PreferenceOwnerKind.HABIT: (habit_id, f"{HABITS_PREFIX}/{habit_id}/preference"),
            PreferenceOwnerKind.TASK: (task_id, f"{TASKS_PREFIX}/{task_id}/preference"),
        }

    def path(self, kind: PreferenceOwnerKind) -> str:
        return self._by_kind[kind][1]

    def owner_id(self, kind: PreferenceOwnerKind) -> UUID:
        return UUID(self._by_kind[kind][0])


async def an_owner_of_each_kind(client: httpx.AsyncClient, headers: dict[str, str]) -> Owned:
    """An Area, a habit and a task, created through the routes that create them."""
    area = await client.post(
        AREAS_PREFIX, json={"name": f"Fitness {uuid4().hex[:8]}"}, headers=headers
    )
    assert area.status_code == HTTPStatus.CREATED, area.text
    area_id = area.json()["area"]["id"]

    habit = await client.post(
        HABITS_PREFIX,
        json={
            "areaId": area_id,
            "title": "Anki",
            "cadence": {"kind": "daily"},
            "minDurationMinutes": 15,
        },
        headers=headers,
    )
    assert habit.status_code == HTTPStatus.CREATED, habit.text

    task = await client.post(
        TASKS_PREFIX, json={"areaId": area_id, "title": "Essay"}, headers=headers
    )
    assert task.status_code == HTTPStatus.CREATED, task.text
    return Owned(area_id=area_id, habit_id=habit.json()["id"], task_id=task.json()["id"])


def hold_the_window_open_on_the_next_read(monkeypatch: pytest.MonkeyPatch, window: Window) -> None:
    """Make the next read of an owner's preference wait inside the window before answering.

    A wrapper around the real read rather than a substituted repository: the app builds its own
    dependencies, so there is nothing here to inject into. It fires once, so the racing request
    runs through the seam untouched rather than waiting on an event that is already set.
    """
    reading = PreferenceRepository.find
    held = False

    async def find_inside_the_window(
        repository: PreferenceRepository, owner: PreferenceOwner
    ) -> PreferenceRecord | None:
        nonlocal held
        found = await reading(repository, owner)
        if not held:
            held = True
            await window.hold()
        return found

    monkeypatch.setattr(PreferenceRepository, "find", find_inside_the_window)


async def stored_windows(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> list[list[dict[str, str]]]:
    """The window list of every preference row this tenant holds, read on its own connection."""
    async with sessions() as session:
        stored = await PreferenceRepository(session, tenant_id).list_all()
    return [[dict(window) for window in row.windows] for row in stored]


def a_preference(owner: PreferenceOwner, window: LocalTimeWindow) -> Preference:
    """One owner's preference over a single window, as the entity a replacement stores."""
    return Preference(
        owner=owner,
        windows=(window,),
        strength=PreferenceStrength.SOFT,
        preferred_duration_minutes=None,
        max_per_day_minutes=None,
    )


def owner_identity(kind: PreferenceOwnerKind) -> tuple[str, ...]:
    """The columns one preference per owner is stated over, for this kind of owner.

    Read from the repository's own kind-to-column mapping, which is what the replacement's conflict
    target is built from, so this cannot name a different pair than the write does.
    """
    return (TENANT_ID_COLUMN, OWNER_COLUMN[kind].key)


# --------------------------------------------------------------------------------
# The two races: what each caller is answered, and what ends up stored
# --------------------------------------------------------------------------------


async def test_two_replacements_racing_one_owner_both_answer_200(
    wired: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Both requests declare a preference for an owner that has none, so both reads see nothing and
    # the second write is the one that meets a row. 200 rather than merely not-500: the loser's
    # request was well formed and its declaration is what the owner ends up with.
    headers = await signed_in(wired, owner)
    owned = await an_owner_of_each_kind(wired, headers)
    path = owned.path(PreferenceOwnerKind.AREA)
    window = Window(hold_for=WINDOW_SECONDS)
    hold_the_window_open_on_the_next_read(monkeypatch, window)

    async def replace_inside_the_window() -> httpx.Response:
        """The request that lands whole while the other one is between its read and its write."""
        await window.open.wait()
        answered = await wired.put(path, json=WRITTEN_FIRST, headers=headers)
        window.closed.set()
        return answered

    writes_second, writes_first = await asyncio.wait_for(
        asyncio.gather(
            wired.put(path, json=WRITTEN_SECOND, headers=headers), replace_inside_the_window()
        ),
        timeout=WINDOW_SECONDS * 2,
    )

    assert writes_first.status_code == HTTPStatus.OK, writes_first.text
    assert writes_second.status_code == HTTPStatus.OK, writes_second.text
    # Each caller is told what it declared, because each read the state its own write left.
    assert writes_first.json()["declared"]["windows"] == STORED_FIRST
    assert writes_second.json()["declared"]["windows"] == STORED_SECOND
    assert await stored_windows(sessions, owner.tenant_id) == [STORED_SECOND]


async def test_a_removal_inside_the_window_does_not_leave_a_replacement_unstored(
    wired: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The other side of the same read: here the row IS there when the replacement reads it and is
    # gone when the replacement writes, which is the interleaving an insert-or-update decision
    # gets wrong in the opposite direction.
    headers = await signed_in(wired, owner)
    owned = await an_owner_of_each_kind(wired, headers)
    path = owned.path(PreferenceOwnerKind.AREA)
    seeded = await wired.put(path, json=WRITTEN_FIRST, headers=headers)
    assert seeded.status_code == HTTPStatus.OK, seeded.text

    # Armed after the seeding, so the window opens on the replacement's read rather than on one of
    # the reads the seeding took.
    window = Window(hold_for=WINDOW_SECONDS)
    hold_the_window_open_on_the_next_read(monkeypatch, window)

    async def remove_inside_the_window() -> httpx.Response:
        await window.open.wait()
        answered = await wired.delete(path, headers=headers)
        window.closed.set()
        return answered

    replaced, removed = await asyncio.wait_for(
        asyncio.gather(
            wired.put(path, json=WRITTEN_SECOND, headers=headers), remove_inside_the_window()
        ),
        timeout=WINDOW_SECONDS * 2,
    )

    assert removed.status_code == HTTPStatus.OK, removed.text
    assert replaced.status_code == HTTPStatus.OK, replaced.text
    # A 200 carrying `declared: null` is the defect: the caller is told a declaration was accepted
    # and has no way to tell that nothing was stored.
    assert replaced.json()["declared"] is not None, (
        "the replacement answered 200 for a declaration it did not store"
    )
    assert replaced.json()["declared"]["windows"] == STORED_SECOND
    assert await stored_windows(sessions, owner.tenant_id) == [STORED_SECOND]


async def test_a_replacement_waits_for_an_uncommitted_one_rather_than_being_refused(
    wired: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
) -> None:
    # The third interleaving, and the one no request-level seam can reach: the racing replacement
    # has written and NOT committed, so the index has nothing to refuse yet and Postgres makes the
    # second writer wait for the first transaction to end. Driven over two connections of this
    # test's own, because holding a request's transaction open past its response is not something
    # the app offers.
    headers = await signed_in(wired, owner)
    owned = await an_owner_of_each_kind(wired, headers)
    area = PreferenceOwner(
        kind=PreferenceOwnerKind.AREA, id=owned.owner_id(PreferenceOwnerKind.AREA)
    )

    async def replace_over_a_second_connection() -> None:
        async with sessions() as second, second.begin():
            await PreferenceRepository(second, owner.tenant_id).upsert(
                a_preference(area, WINDOW_WRITTEN_SECOND), created_at=NOW
            )

    async with sessions() as first, first.begin():
        await PreferenceRepository(first, owner.tenant_id).upsert(
            a_preference(area, WINDOW_WRITTEN_FIRST), created_at=NOW
        )
        waiting = asyncio.create_task(replace_over_a_second_connection())
        _, pending = await asyncio.wait([waiting], timeout=BLOCKED_SECONDS)
        # Not cancelled on the timeout: the claim is that it is still waiting, and a refusal would
        # have finished the task with an `IntegrityError` instead.
        assert waiting in pending, (
            "the second replacement did not wait for the uncommitted first one"
        )

    await asyncio.wait_for(waiting, timeout=WINDOW_SECONDS)
    assert await stored_windows(sessions, owner.tenant_id) == [STORED_SECOND]


# --------------------------------------------------------------------------------
# The guarantee: one row per owner, and the index that is still what says so
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind", list(PreferenceOwnerKind), ids=[kind.value for kind in PreferenceOwnerKind]
)
async def test_a_second_row_for_one_owner_is_refused_by_that_owners_own_index(
    wired: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    kind: PreferenceOwnerKind,
) -> None:
    # The replacement names this index as its conflict target, so the index decides what an
    # existing row is as well as guaranteeing there is only one of them. The duplicate is written
    # around the application, which is what makes this the table's guarantee rather than the
    # statement's.
    headers = await signed_in(wired, owner)
    owned = await an_owner_of_each_kind(wired, headers)
    declared = await wired.put(owned.path(kind), json=WRITTEN_FIRST, headers=headers)
    assert declared.status_code == HTTPStatus.OK, declared.text

    async with sessions() as session, session.begin():
        with pytest.raises(IntegrityError) as refused:
            async with session.begin_nested():
                await session.execute(
                    insert(PreferenceRow).values(
                        id=uuid4(),
                        tenant_id=owner.tenant_id,
                        owner_kind=kind.value,
                        windows=[EVENING],
                        strength="soft",
                        created_at=NOW,
                        **{OWNER_COLUMN[kind].key: owned.owner_id(kind)},
                    )
                )

    assert refused_index(refused.value) == the_unique_index_over(
        PreferenceRow, owner_identity(kind)
    )


async def test_each_owner_reference_carries_a_unique_index_in_the_migrated_schema(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Crossed rather than restated: the columns come from the table's own declaration and the
    # three an owner is addressed through have to be among them, so a reference that lost its
    # index is red here rather than discovered as two rows for one owner.
    declared = {
        the_unique_index_over(PreferenceRow, owner_identity(kind)): owner_identity(kind)
        for kind in PreferenceOwnerKind
    }
    assert len(declared) == len(PreferenceOwnerKind)

    async with sessions() as session:
        migrated = {
            str(row.index_name): (bool(row.is_unique), tuple(row.columns))
            for row in await session.execute(
                text(
                    "SELECT i.relname AS index_name, ix.indisunique AS is_unique, "
                    "  array_agg(a.attname ORDER BY k.ord) AS columns "
                    "FROM pg_class t "
                    "JOIN pg_index ix ON ix.indrelid = t.oid "
                    "JOIN pg_class i ON i.oid = ix.indexrelid "
                    "JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE "
                    "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
                    "WHERE i.relname = ANY(:names) "
                    "GROUP BY i.relname, ix.indisunique"
                ),
                {"names": list(declared)},
            )
        }

    assert migrated == {name: (True, columns) for name, columns in declared.items()}
