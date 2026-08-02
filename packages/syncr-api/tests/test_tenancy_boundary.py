"""The tenancy boundary: the schema rules and the SQL rule, asserted mechanically.

Four rules live here, and each applies to every table that arrives later as much as to the
ones present today.

The positive controls are what keep that true. Each rule is also run against a deliberately
broken model built in a metadata of its own, because "every domain table carries a tenant id"
passes on a schema whose tables all happen to, and goes on passing after someone adds one that
does not.

The rules:

1. Every table that is not an identity table carries a non-null ``tenant_id``.
2. Every such table has an index whose FIRST column is ``tenant_id``, and no multi-column
   index leads with anything else.
3. No table except ``sessions`` carries a ``user_id``.
4. Every statement any module of a scoped package builds carries a tenant predicate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from sqlalchemy import MetaData, Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.sqltypes import NullType

from syncr_api.accounts import models as accounts_models
from syncr_api.core.orm import Base
from syncr_api.core.repository import TenantScopedRepository
from syncr_api.core.tenancy import (
    IDENTITY_TABLES,
    SESSIONS_TABLE,
    TENANT_ID_COLUMN,
    TENANTS_TABLE,
    USER_ID_COLUMN,
    TenantScoped,
)
from syncr_api.plans import models as plans_models
from tests.boundaries import (
    REPOSITORY_MODULE_NAME,
    bare_statement_calls,
    mapped_classes,
    package_modules,
    packages_with_scoped_tables,
)
from tests.control_models import ControlBase, ScopedThing, table_of

if TYPE_CHECKING:
    from pathlib import Path


# The tables in the metadata Alembic diffs. Every models module is imported before the
# metadata is read, so a feature module whose models nothing else imports still comes
# under these rules rather than falling outside them silently.
@pytest.fixture(autouse=True)
def _every_models_module_imported(source_root: Path) -> list[type]:
    return mapped_classes(source_root)


ALEMBIC_TABLE = "alembic_version"

# The one table allowed to name a user, because authentication resolves a subject before
# it resolves a scope and both answers are wanted there.
TABLES_ALLOWED_A_USER_ID = frozenset({SESSIONS_TABLE})


def scoped_tables() -> list[str]:
    """Every table the tenancy rules apply to."""
    return sorted(
        name
        for name in Base.metadata.tables
        if name not in IDENTITY_TABLES and name != ALEMBIC_TABLE
    )


def missing_tenant_id(metadata: MetaData) -> list[str]:
    """Tables that should carry a non-null ``tenant_id`` and do not."""
    failures = []
    for name, table in sorted(metadata.tables.items()):
        if name in IDENTITY_TABLES or name == ALEMBIC_TABLE:
            continue
        column = table.columns.get(TENANT_ID_COLUMN)
        if column is None:
            failures.append(f"{name} has no {TENANT_ID_COLUMN}")
        elif column.nullable:
            failures.append(f"{name}.{TENANT_ID_COLUMN} is nullable")
    return failures


def indexes_not_leading_with_tenant(metadata: MetaData) -> list[str]:
    """Tables whose index design does not put the scope first.

    Two failures are reported: a scoped table with no index leading on ``tenant_id`` at
    all, and any multi-column index on such a table that leads with something else. A
    query is scoped whether or not its other predicates are selective, so an index that
    cannot serve the scope first cannot serve the query.
    """
    failures = []
    for name, table in sorted(metadata.tables.items()):
        if name in IDENTITY_TABLES or name == ALEMBIC_TABLE:
            continue
        column_lists = [
            [column.name for column in index.columns] for index in sorted(table.indexes, key=str)
        ]
        if table.primary_key is not None:
            column_lists.append([column.name for column in table.primary_key.columns])
        leading = [columns for columns in column_lists if columns[:1] == [TENANT_ID_COLUMN]]
        if not leading:
            failures.append(f"{name} has no index leading with {TENANT_ID_COLUMN}")
        failures.extend(
            f"{name} has a composite index on {columns} that does not lead with {TENANT_ID_COLUMN}"
            for columns in column_lists
            if len(columns) > 1 and columns[0] != TENANT_ID_COLUMN
        )
    return failures


def tables_carrying_a_user_id(metadata: MetaData) -> list[str]:
    """Tables with a ``user_id`` column that are not allowed one."""
    return sorted(
        name
        for name, table in metadata.tables.items()
        if USER_ID_COLUMN in table.columns and name not in TABLES_ALLOWED_A_USER_ID
    )


def test_every_scoped_table_carries_a_non_null_tenant_id() -> None:
    assert missing_tenant_id(Base.metadata) == []


def test_every_scoped_table_has_an_index_leading_with_the_tenant() -> None:
    assert indexes_not_leading_with_tenant(Base.metadata) == []


def test_no_table_carries_a_user_id_except_sessions() -> None:
    assert tables_carrying_a_user_id(Base.metadata) == [], (
        "a user dimension on a table that holds a plan means the tenancy granularity "
        "drifted: a tenant holds exactly one user, permanently, so a plan row has no "
        "user to disambiguate between."
    )


def test_the_identity_exemption_covers_exactly_the_tables_it_names() -> None:
    # The exemption set is what lets a table skip every rule above, so it is asserted rather
    # than trusted. Each entry has to be argued for in a diff, and each one here is: three
    # establish a tenant, a person, and a browser, and the fourth establishes a CLIENT. All
    # four are read by something other than a tenant, because all four run before one is
    # known, and `core/tenancy.py` states each reason next to its name.
    assert {"tenants", "users", "sessions", "oauth_clients"} == IDENTITY_TABLES
    assert set(Base.metadata.tables) >= IDENTITY_TABLES


def test_the_sessions_table_is_the_only_place_a_principal_and_a_scope_meet() -> None:
    sessions = Base.metadata.tables[SESSIONS_TABLE]

    assert TENANT_ID_COLUMN in sessions.columns
    assert USER_ID_COLUMN in sessions.columns
    assert sessions.columns[TENANT_ID_COLUMN].nullable is False
    assert sessions.columns[USER_ID_COLUMN].nullable is False


def test_one_user_per_tenant_is_enforced_by_the_schema() -> None:
    tenant_id = Base.metadata.tables["users"].columns[TENANT_ID_COLUMN]

    assert tenant_id.unique is True, (
        "without a unique index on users.tenant_id, a second user in a tenant is "
        "rejected by nothing, and every table that assumed one user per tenant is wrong"
    )


# --------------------------------------------------------------------------------
# The SQL rule. A scoped repository's statements are compiled and read, and every
# scoped package's repository module is read for a statement built without the scope.
# --------------------------------------------------------------------------------


def compiled(statement: object) -> str:
    return str(statement)


def test_a_scoped_repository_cannot_be_built_without_a_tenant() -> None:
    with pytest.raises(TypeError):
        TenantScopedRepository(AsyncSession())  # type: ignore[call-arg]  # the point of the test


def test_every_statement_a_scoped_repository_builds_carries_a_tenant_predicate() -> None:
    tenant_id = uuid4()
    # An unbound session: statements are built and read here, never executed, and the
    # integration tier is where the executed form is asserted.
    repository = TenantScopedRepository(AsyncSession(), tenant_id)

    for statement in (
        repository.scoped_select(ScopedThing),
        repository.scoped_update(ScopedThing),
        repository.scoped_delete(ScopedThing),
    ):
        assert "scoped_things.tenant_id = " in compiled(statement), compiled(statement)
    assert repository.tenant_id == tenant_id


def test_the_sql_check_reports_a_statement_built_without_the_scope() -> None:
    # The control for the assertions above: the same reading applied to the statement a
    # repository would produce if it bypassed the base and called `select` itself.
    sql = compiled(select(ScopedThing))

    assert "WHERE" not in sql, sql


def test_no_repository_over_a_scoped_table_builds_a_statement_without_the_scope(
    source_root: Path,
) -> None:
    # The half the compiled assertions above cannot reach: nothing forces a repository to
    # USE the base's helpers. A module that subclasses `TenantScopedRepository` and then
    # writes `select(PlanRevision).where(PlanRevision.id == ...)` would satisfy every other
    # test in this file.
    #
    # EVERY module of the package is read, not only `repository.py`. Plan storage splits its
    # repositories by concern, one per module, so a rule that read one file would cover one
    # of them and leave the rest outside it.
    violations = {}
    for package in sorted(packages_with_scoped_tables(mapped_classes(source_root))):
        assert (source_root / package / REPOSITORY_MODULE_NAME).exists(), (
            f"{package} owns a scoped table and has no repository module"
        )
        for module in package_modules(source_root, package):
            if bare := bare_statement_calls(module.read_text(encoding="utf-8")):
                violations[f"{package}/{module.name}"] = bare

    assert violations == {}, (
        f"{violations}. Build these from `self.scoped_select`, `self.scoped_update`, or "
        "`self.scoped_delete`, so the tenant predicate is applied by the base rather "
        "than remembered by each method."
    )


def test_the_repository_walk_examines_the_packages_that_own_a_scoped_table(
    source_root: Path,
) -> None:
    # What used to stand here was a tripwire asserting NO package owned a scoped table, so
    # the rule above was armed and vacuous. The settings tables are the first, so the rule
    # is live: this asserts the walk finds a subject, which is what the tripwire's failure
    # was the notice of.
    scoped = packages_with_scoped_tables(mapped_classes(source_root))

    assert scoped, (
        "the repository rule above iterates over scoped packages and found none, so it "
        "proves nothing. Either the models walk stopped seeing them or the tables went away."
    )


def test_the_repository_walk_names_the_package_of_a_scoped_table() -> None:
    # The discovery half's control. Without it, "no package owns a scoped table" and "the
    # walk cannot see one" are indistinguishable.
    assert packages_with_scoped_tables([plans_models.PlanRevision]) == {"plans"}
    assert packages_with_scoped_tables([accounts_models.BrowserSession]) == set()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("rows = select(PlanRevision).where(PlanRevision.id == revision_id)", ["select"]),
        ("await self._session.execute(update(Pin).values(pinned=True))", ["update"]),
        ("await self._session.execute(delete(Pin))", ["delete"]),
        ("rows = self.scoped_select(PlanRevision).where(PlanRevision.id == revision_id)", []),
        ("stmt = self.scoped_update(Pin).values(pinned=True)", []),
        ("self._session.add(PlanRevision(id=revision_id))", []),
    ],
)
def test_the_bare_statement_check_reports_what_it_should(source: str, expected: list[str]) -> None:
    assert bare_statement_calls(source) == expected


def test_the_identity_repository_is_exempt_and_would_otherwise_be_reported(
    source_root: Path,
) -> None:
    # `accounts/repository.py` legitimately calls `select` and `update` directly, because
    # its tables are read before a tenant is known. This asserts the exemption is doing
    # real work rather than being untested: the module WOULD be reported if its package
    # owned a scoped table.
    accounts_repository = source_root / "accounts" / REPOSITORY_MODULE_NAME

    assert bare_statement_calls(accounts_repository.read_text(encoding="utf-8")) != []
    assert "accounts" not in packages_with_scoped_tables(mapped_classes(source_root))


@pytest.mark.parametrize(
    ("check", "expected"),
    [
        (missing_tenant_id, ["unscoped_things has no tenant_id"]),
        (
            indexes_not_leading_with_tenant,
            [
                "unscoped_things has no index leading with tenant_id",
                "unscoped_things has a composite index on ['label', 'id'] that does not "
                "lead with tenant_id",
            ],
        ),
    ],
)
def test_the_schema_checks_report_a_table_that_broke_the_rule(
    check: object, expected: list[str]
) -> None:
    # `scoped_things` is in the same metadata and satisfies both rules, so each check is
    # shown to distinguish rather than to flag everything it is handed.
    assert callable(check)
    assert check(ControlBase.metadata) == expected


def test_the_user_id_check_reports_a_table_that_names_a_user() -> None:
    assert tables_carrying_a_user_id(ControlBase.metadata) == ["unscoped_things"]


def test_the_scoped_column_carries_a_type_of_its_own_rather_than_a_borrowed_one() -> None:
    # The condition the explicit type exists for. A column produced through
    # `declared_attr` takes none from its annotation, and falls back to inferring one
    # from its foreign key's target, so in a metadata where `tenants` is absent it is
    # left typeless: every statement still compiles and only CREATE TABLE fails, in a
    # tier a unit-only run skips.
    class OrphanBase(DeclarativeBase):
        metadata = MetaData()

    class Orphan(OrphanBase, TenantScoped):
        __tablename__ = "orphan_things"

        id: Mapped[UUID] = mapped_column(primary_key=True)

    column = table_of(Orphan).columns[TENANT_ID_COLUMN]

    assert TENANTS_TABLE not in OrphanBase.metadata.tables
    assert not isinstance(column.type, NullType), (
        "the scoped column has no SQL type of its own, so a table carrying it cannot be "
        "created wherever its foreign key target is not in the same metadata"
    )
    assert isinstance(column.type, Uuid)


def test_the_scoped_mixin_produces_a_usable_column_per_table() -> None:
    # A ForeignKey object cannot be shared between mapped classes, so a mixin that
    # assigned one column would fail on the second table rather than on the first.
    for column in (
        table_of(ScopedThing).columns[TENANT_ID_COLUMN],
        table_of(accounts_models.BrowserSession).columns[TENANT_ID_COLUMN],
    ):
        assert column.nullable is False
        # The type is asserted, not just the nullability. A column produced through
        # `declared_attr` takes no type from its annotation, so dropping the explicit one
        # leaves it typeless: every statement still compiles and only CREATE TABLE fails,
        # in a tier a unit-only run skips.
        assert not isinstance(column.type, NullType), (
            "the scoped column has no SQL type, so a table carrying it cannot be created"
        )
        assert isinstance(column.type, Uuid)


def test_a_scoped_model_records_instants_as_aware_datetimes() -> None:
    # The whole product is instant arithmetic, so a naive column would be a silent
    # source of wrong answers rather than an error.
    thing = ScopedThing(id=uuid4(), tenant_id=uuid4(), recorded_at=datetime.now(UTC))

    assert thing.recorded_at.tzinfo is not None
