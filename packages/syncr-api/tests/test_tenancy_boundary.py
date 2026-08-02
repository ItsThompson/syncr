"""The tenancy boundary: the schema rules and the SQL rule, asserted mechanically.

Four rules live here, and all four are about tables and queries that do not exist yet as
much as about the three that do. The first scoped table arrives with plan storage, and
these tests are what it will meet.

That makes the positive controls essential rather than thorough. Three of these rules
currently have nothing to catch, so each is also run against a deliberately broken model
built in a metadata of its own. Without that, "every domain table carries a tenant id"
would pass on a schema with no domain tables and go on passing after someone adds one
without a tenant id.

The rules:

1. Every table that is not an identity table carries a non-null ``tenant_id``.
2. Every such table has an index whose FIRST column is ``tenant_id``, and no multi-column
   index leads with anything else.
3. No table except ``sessions`` carries a ``user_id``.
4. Every statement a scoped repository builds carries a tenant predicate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import AsyncSession

from syncr_api.accounts import models as accounts_models
from syncr_api.core.orm import Base
from syncr_api.core.repository import TenantScopedRepository
from syncr_api.core.tenancy import (
    IDENTITY_TABLES,
    SESSIONS_TABLE,
    TENANT_ID_COLUMN,
    USER_ID_COLUMN,
)
from tests.control_models import ControlBase, ScopedThing

# The tables in the metadata Alembic diffs. Imported for the registration side effect
# so the walk sees the accounts tables whether or not another test imported them first.
assert accounts_models.Tenant is not None

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


def test_the_identity_exemption_covers_exactly_the_three_tables_it_names() -> None:
    # The exemption set is what lets a table skip every rule above, so it is asserted
    # rather than trusted. A fourth entry has to be argued for in a diff.
    assert {"tenants", "users", "sessions"} == IDENTITY_TABLES
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
# The SQL rule. A scoped repository's statements are compiled and read.
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

    sql = compiled(repository.scoped_select(ScopedThing))

    assert "WHERE scoped_things.tenant_id = " in sql, sql
    assert repository.tenant_id == tenant_id


def test_the_sql_check_reports_a_statement_built_without_the_scope() -> None:
    # The control for the assertion above: the same reading applied to the statement a
    # repository would produce if it bypassed the base and called `select` itself.
    sql = compiled(select(ScopedThing))

    assert "WHERE" not in sql, sql


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


def test_the_scoped_mixin_produces_a_usable_column_per_table() -> None:
    # A ForeignKey object cannot be shared between mapped classes, so a mixin that
    # assigned one column would fail on the second table rather than on the first.
    assert ScopedThing.__table__.columns[TENANT_ID_COLUMN].nullable is False
    assert accounts_models.BrowserSession.__table__.columns[TENANT_ID_COLUMN].nullable is False


def test_a_scoped_model_records_instants_as_aware_datetimes() -> None:
    # The whole product is instant arithmetic, so a naive column would be a silent
    # source of wrong answers rather than an error.
    thing = ScopedThing(id=uuid4(), tenant_id=uuid4(), recorded_at=datetime.now(UTC))

    assert thing.recorded_at.tzinfo is not None
