"""The two database families, read out of the exposition a scraper reads.

The pool gauge is driven by CHECKING OUT connections and watching it rise, then releasing them and
watching it fall, because a gauge asserted only at rest is a gauge nobody has seen move.

The read histogram is driven through a real repository against a real database, so the wrap the
scoped base installs is exercised where it actually runs. One test asserts the failing exit is timed
too: a read that raises after a lock wait is the reading an operator most wants.

The census at the bottom is what makes the metric's coverage a property of the package rather than
of what a decorator was remembered on. It derives the repositories from the modules; the reasoning
behind its population and its edge is in ``tests/repository_census.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from prometheus_client import generate_latest
from sqlalchemy import text

from syncr_api.accounts.repository import (
    SessionRepository,
    TenantRepository,
    UserRepository,
)
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.db_metrics import READ_BUCKETS, measure_reads
from syncr_api.core.repository import TenantScopedReader
from syncr_api.oauth.repository import PresentedCredentialRepository
from syncr_common.metrics import REGISTRY
from tests.repository_census import (
    outside_the_hook,
    reads,
    repository_classes,
    shared_labels,
    untimed,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

POOL_IN_USE = "syncr_db_pool_in_use"
READ_COUNT = "syncr_db_query_duration_seconds_count"


def sample(name: str, **labels: str) -> float:
    """One sample out of the rendered exposition. Zero when the series does not exist yet."""
    wanted = ",".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
    prefix = f"{name}{{{wanted}}} " if wanted else f"{name} "
    for line in generate_latest(REGISTRY).decode().splitlines():
        if line.startswith(prefix):
            return float(line.removeprefix(prefix))
    return 0.0


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    """An engine of this module's own, so checking connections out disturbs no other suite."""
    built = create_db_engine(live_database_url)
    try:
        yield built
    finally:
        await built.dispose()


class TestThePoolGauge:
    async def test_it_is_present_before_any_connection_is_taken(self, engine: AsyncEngine) -> None:
        """A gauge nothing has set yet must still be readable, or the alert has no series.

        Ticket 30's lesson stated as a test: a gauge set only when work happens is absent exactly
        when the work is not happening.
        """
        assert POOL_IN_USE in generate_latest(REGISTRY).decode()

    async def test_it_rises_while_a_connection_is_checked_out_and_falls_after(
        self, engine: AsyncEngine
    ) -> None:
        at_rest = sample(POOL_IN_USE)

        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            while_held = sample(POOL_IN_USE)

        assert while_held - at_rest == 1.0
        assert sample(POOL_IN_USE) == at_rest

    async def test_two_connections_read_as_two(self, engine: AsyncEngine) -> None:
        at_rest = sample(POOL_IN_USE)

        async with engine.connect() as first, engine.connect() as second:
            await first.execute(text("SELECT 1"))
            await second.execute(text("SELECT 1"))

            assert sample(POOL_IN_USE) - at_rest == 2.0


class TestTheReadHistogram:
    async def test_the_buckets_are_the_latency_budgets_rather_than_the_library_defaults(
        self,
    ) -> None:
        """A read at 100 ms has spent the whole week-assembly budget in one call."""
        assert 0.1 in READ_BUCKETS
        assert max(READ_BUCKETS) == float("inf")

    async def test_a_scoped_repository_read_is_timed_under_its_own_class_and_method(
        self, engine: AsyncEngine
    ) -> None:
        labels = {"repository": "TenantRepository", "method": "list_ids"}
        before = sample(READ_COUNT, **labels)

        async with create_sessionmaker(engine)() as session:
            await TenantRepository(session).list_ids()

        assert sample(READ_COUNT, **labels) - before == 1.0

    async def test_the_presented_credential_reads_are_timed_under_their_own_class(
        self, engine: AsyncEngine
    ) -> None:
        """The token endpoint's four reads. Outside the hook, so the decorator is what times them.

        The method names are crossed against the class's own read surface, so a fifth read added
        without being driven here reddens rather than going unmeasured.
        """
        unknown = "a digest no row carries"
        methods = ("find_client", "find_code", "find_grant", "find_refresh_token")
        assert reads(PresentedCredentialRepository) == methods

        labels = {"repository": PresentedCredentialRepository.__name__}
        before = {name: sample(READ_COUNT, method=name, **labels) for name in methods}

        async with create_sessionmaker(engine)() as session:
            credentials = PresentedCredentialRepository(session)
            await credentials.find_client(unknown)
            await credentials.find_code(unknown)
            await credentials.find_grant(uuid4())
            await credentials.find_refresh_token(unknown)

        assert {
            name: sample(READ_COUNT, method=name, **labels) - before[name] for name in methods
        } == dict.fromkeys(methods, 1.0)

    async def test_a_read_that_raises_is_timed_too(self, engine: AsyncEngine) -> None:
        """A read failing after a lock wait is a latency reading, not a sample to drop."""

        class BrokenReader(TenantScopedReader):
            async def read(self) -> None:
                raise RuntimeError("the statement did not come back")

        labels = {"repository": "BrokenReader", "method": "read"}
        before = sample(READ_COUNT, **labels)

        async with create_sessionmaker(engine)() as session:
            with pytest.raises(RuntimeError):
                await BrokenReader(session, uuid4()).read()

        assert sample(READ_COUNT, **labels) - before == 1.0

    async def test_the_wrap_keeps_the_method_recognisable(self) -> None:
        """The public surface is what three storage rules are asserted over, so it must survive."""

        class Reader(TenantScopedReader):
            async def read_one(self) -> int:
                """A docstring a boundary test may read."""
                return 1

        assert Reader.read_one.__name__ == "read_one"
        assert Reader.read_one.__doc__ == "A docstring a boundary test may read."

    async def test_a_private_method_is_not_a_series(self) -> None:
        """The label set is bounded by the public surface, not by every helper a class holds."""

        class Reader(TenantScopedReader):
            async def _helper(self) -> int:
                return 1

        assert not hasattr(Reader._helper, "__wrapped__")

    async def test_an_inherited_method_is_timed_once_under_the_class_that_defined_it(self) -> None:
        """Two series for one call would double every figure the dashboard draws."""

        class Base(TenantScopedReader):
            async def read_one(self) -> int:
                return 1

        class Derived(Base):
            pass

        assert Derived.read_one is Base.read_one


class TestTheExplicitApplication:
    def test_it_wraps_only_what_a_class_defines(self) -> None:
        class Plain:
            async def read(self) -> int:
                return 1

            def sync_read(self) -> int:
                return 1

        measure_reads(Plain)

        assert hasattr(Plain.read, "__wrapped__")
        assert not hasattr(Plain.sync_read, "__wrapped__")


class UnscopedRepository:
    """A repository outside the hook and outside the census's population.

    Declared here rather than inside a test, so both controls read the same class: the census walks
    the api package, so nothing in this module is ever in the population it asserts over.
    """

    async def find(self) -> int:
        return 1


@measure_reads
class DecoratedRepository:
    async def find(self) -> int:
        return 1


class HookedRepository(TenantScopedReader):
    """The other mechanism, with nothing on it: the base is what wraps this one's read."""

    async def find(self) -> int:
        return 1


class TestTheRepositoryCensus:
    def test_every_repository_this_package_declares_is_timed(self) -> None:
        """The durable half: a repository the hook cannot reach and nobody decorated is a hole."""
        assert untimed(repository_classes()) == (), (
            "these reads carry no series under "
            "syncr_db_query_duration_seconds{repository=<class>}: either extend TenantScopedReader "
            "or, where the tenant is not known until the read answers, carry measure_reads"
        )

    def test_the_walk_finds_the_repositories_that_are_outside_the_hook(self) -> None:
        """The positive control on the population: a census over nothing passes over nothing.

        A lower bound rather than the whole set, because the set grows with the package and a test
        asserting today's members would fail on a fifth one that is perfectly well timed. Each of
        these defines a read as well, so none of them is cleared by having nothing to time.
        """
        read_before_a_tenant_is_known = (
            PresentedCredentialRepository,
            SessionRepository,
            TenantRepository,
            UserRepository,
        )

        assert set(read_before_a_tenant_is_known) <= set(outside_the_hook(repository_classes()))
        assert all(reads(one) for one in read_before_a_tenant_is_known)

    def test_the_population_reaches_a_repository_outside_a_repository_module(self) -> None:
        """Which is what keying on the class name buys over walking ``repository.py``."""
        elsewhere = [
            one for one in repository_classes() if not one.__module__.endswith(".repository")
        ]

        assert elsewhere != []

    def test_the_population_reaches_the_base_the_hook_is_installed_on(self) -> None:
        """Which is what adding the base by inheritance buys: nothing wraps the base itself."""
        assert TenantScopedReader in outside_the_hook(repository_classes())

    def test_an_undecorated_repository_outside_the_hook_is_reported(self) -> None:
        """The bite, without waiting for someone to write one: the same reading, a broken input."""
        assert untimed((UnscopedRepository,)) == ("tests.test_db_metrics.UnscopedRepository.find",)

    def test_the_decorator_is_what_clears_it(self) -> None:
        """So the reading responds to the wrap rather than to what the class is called."""
        assert untimed((DecoratedRepository,)) == ()

    def test_the_hook_clears_a_subclass_that_carries_nothing(self) -> None:
        """The reading is over both mechanisms, so it reddens when either one stops working."""
        assert untimed((HookedRepository,)) == ()

    def test_no_two_repositories_answer_to_one_label(self) -> None:
        """Two classes sharing a name share a series, and one would hide the other's absence."""
        assert shared_labels(repository_classes()) == ()
