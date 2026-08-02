"""The tenancy rule the schema is built on, and the mixin that applies it.

Every table that holds a user's plan carries a non-null ``tenant_id`` from the first
migration that creates a table at all. Retrofitting a scope after data exists is a
migration nobody wants to write, so the schema is multi-tenant before it has a second
tenant to serve.

A tenant holds exactly one user, permanently. syncr is not a team calendar, a shared
calendar, or a meeting scheduler, and onboarding more people means more independent
tenants rather than more users inside one. So no scoped table carries a ``user_id``:
plans, pins, revisions, outcomes, and adjustments have no user dimension to disagree
about. ``sessions`` is the single exception, because authentication resolves a subject
before it resolves a scope, and both answers are wanted there.

Row-level security is NOT enabled. Application-level scoping plus a test that
inspects generated SQL gives the same guarantee while one tenant has nothing to leak
between, and every composite index leads with ``tenant_id``, so turning RLS on later
needs no re-indexing. ``docs/runbooks/bootstrap-first-user.md`` records when to
revisit it.
"""

# NO `from __future__ import annotations` in this module, deliberately. SQLAlchemy
# resolves a mixin's `Mapped[...]` annotation in the namespace of the SUBCLASS that
# applies the mixin, not in this module's. With postponed evaluation the annotation is a
# string, so every model module applying the mixin would have to import whatever name is
# written below or fail to map at import. Evaluating it here makes the annotation a real
# object that resolves once, correctly, for every subclass.
from uuid import UUID

from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

TENANT_ID_COLUMN = "tenant_id"
USER_ID_COLUMN = "user_id"

TENANTS_TABLE = "tenants"
USERS_TABLE = "users"
SESSIONS_TABLE = "sessions"

# The tables that establish identity rather than hold a plan. They are exempt from
# the scoped-table rules above, and each exemption is answerable:
#
#   tenants   is the scope. Its own `id` is what every other table's tenant_id
#             references, so a tenant_id column would reference itself.
#   users     is read by email at sign-in, before any tenant is known. It carries a
#             UNIQUE tenant_id, which is what makes the tenant-to-user relation 1:1
#             and permanent rather than conventional.
#   sessions  is read by the presented credential's digest, before any tenant is
#             known. It is the one place a principal and a scope both appear.
#
# Nothing else belongs here. A later table added to this set would be a table whose
# queries no longer have to prove they are scoped, so the set is asserted to be
# exactly these three.
IDENTITY_TABLES = frozenset({TENANTS_TABLE, USERS_TABLE, SESSIONS_TABLE})


class TenantScoped:
    """Declarative mixin carrying the non-null ``tenant_id`` a scoped table needs.

    Applied to a model, it makes the scope structural: the column cannot be forgotten
    on a new table, and it cannot be nullable, so there is no "unscoped row" state
    for a query to have to think about.

    A ``ForeignKey`` object cannot be shared between mapped classes, so the column is
    produced per subclass through ``declared_attr`` rather than assigned once here.

    The mixin declares no index. Which composite index covers a table depends on how
    that table is read, and only the table knows; what every table owes is an index
    whose FIRST column is ``tenant_id``, which
    ``tests/test_tenancy_boundary.py`` enforces.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[UUID]:
        # The SQL type is stated rather than left to be derived. A column declared
        # through `declared_attr` takes no type from the annotation above, so without
        # this it falls back to inferring one from the foreign key's target, which
        # silently produces a typeless column whenever that target is not resolvable.
        return mapped_column(
            Uuid(),
            ForeignKey(f"{TENANTS_TABLE}.id", ondelete="CASCADE"),
            nullable=False,
        )
