"""The base every repository over a scoped table extends.

The tenant is a CONSTRUCTOR dependency. That is the whole design: a per-call tenant
argument is one a caller can omit, and the omission compiles, passes review, and
returns another tenant's rows. A constructor argument cannot be omitted, so an
unscoped repository is not a thing that can be built.

Subclasses build their statements from :meth:`TenantScopedRepository.scoped_select`
rather than from a bare ``select``, so the predicate is applied by the base rather
than remembered by each method. ``tests/test_tenancy_boundary.py`` compiles those
statements and asserts the predicate is in the SQL, and the integration tier records
every statement the database actually executes and asserts the same thing, because a
rule this quiet needs both halves.

Authorization is NOT here. A repository decides what rows are in scope; whether the
caller may act on them is the service layer's decision, made against an explicit
principal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from syncr_api.core.tenancy import TenantScoped

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_domain.identifiers import TenantId


class TenantScopedRepository:
    """Persistence for one tenant's rows, and no other tenant's."""

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
