"""The two bases every repository over a scoped table extends.

The tenant is a CONSTRUCTOR dependency. That is the whole design: a per-call tenant
argument is one a caller can omit, and the omission compiles, passes review, and
returns another tenant's rows. A constructor argument cannot be omitted, so an
unscoped repository is not a thing that can be built.

Subclasses build their statements from ``scoped_select``, ``scoped_update``, and
``scoped_delete`` rather than from a bare ``select``, ``update``, or ``delete``, so the
predicate is applied by the base rather than remembered by each method. Three tests
enforce that: one reads every module of every scoped package and rejects a bare
statement constructor, one compiles what these helpers build and asserts the predicate
is in the SQL, and the integration tier records every statement the database actually
executes and asserts the same. A rule this quiet needs all three.

There are TWO bases because one table's storage rule is that it has no write path beyond
appending. :class:`TenantScopedReader` carries the scope and the read helper and nothing
else, so a repository over an append-only table cannot reach an ``UPDATE`` or a ``DELETE``
builder even by inheritance. A test reads such a repository's whole public surface,
inherited members included, so extending the wrong base fails rather than relying on a
reviewer noticing.

There is deliberately no ``scoped_insert``. A scope is a column value on an insert, not
a predicate, so there would be nothing for a helper to add and nothing for a test to
look for.

Authorization is NOT here. A repository decides what rows are in scope; whether the
caller may act on them is the service layer's decision, made against an explicit
principal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update

from syncr_api.core.tenancy import TenantScoped

if TYPE_CHECKING:
    from sqlalchemy import Delete, Select, Update
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_domain.identifiers import TenantId


class TenantScopedReader:
    """Reads over one tenant's rows, with no write builder at all.

    The base for a repository over a table that has no update and no delete path. What it
    withholds is the point: a subclass appends rows through the session and reads them
    back, and no inherited helper builds a statement that changes one.
    """

    def __init__(self, session: AsyncSession, tenant_id: TenantId) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> TenantId:
        """The tenant every statement this repository builds is scoped to."""
        return self._tenant_id

    def scoped_select[ModelT: TenantScoped](self, model: type[ModelT]) -> Select[tuple[ModelT]]:
        """``SELECT`` over ``model``, already narrowed to this repository's tenant."""
        return select(model).where(model.tenant_id == self._tenant_id)


class TenantScopedRepository(TenantScopedReader):
    """Persistence for one tenant's rows, and no other tenant's."""

    def scoped_update[ModelT: TenantScoped](self, model: type[ModelT]) -> Update:
        """``UPDATE`` over ``model``, already narrowed to this repository's tenant."""
        return update(model).where(model.tenant_id == self._tenant_id)

    def scoped_delete[ModelT: TenantScoped](self, model: type[ModelT]) -> Delete:
        """``DELETE`` over ``model``, already narrowed to this repository's tenant."""
        return delete(model).where(model.tenant_id == self._tenant_id)
