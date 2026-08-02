"""The principal, and the one tenant-ownership check every service calls.

The principal is who the request is for. It is resolved once, at the HTTP edge, from
whichever credential the caller presented, and then passed explicitly into every
service method. An ambient principal read from a context variable is how a new caller
silently skips authorization, so there is no such context variable to read.

:func:`authorize_tenant` raises :class:`~syncr_api.core.errors.NotFound`, never
``Forbidden``. A 403 on someone else's row confirms the row exists, which is a
disclosure in itself; a 404 says only that the caller has nothing by that identifier.
The attempt is logged, because the wire deliberately says nothing and the log is
therefore the only place a probing caller becomes visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.core.errors import NotFound
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from syncr_domain.identifiers import TenantId, UserId

_log = get_logger("syncr.authz")


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated subject of one request.

    A tenant holds exactly one user permanently, so these two are not independent
    coordinates: the pair travels together because authentication resolves a subject
    while authorization resolves a scope, and the two answers are wanted at
    different layers.
    """

    tenant_id: TenantId
    user_id: UserId


def authorize_tenant(principal: Principal, owner_tenant_id: TenantId, *, resource: str) -> None:
    """Raise :class:`NotFound` unless ``owner_tenant_id`` is the principal's tenant.

    ``resource`` names the kind of thing in the message a caller receives, so a 404
    reads as "no such session" rather than as a bare status.
    """
    if owner_tenant_id == principal.tenant_id:
        return
    _log.warning(
        "authz.cross_tenant.denied",
        resource=resource,
        tenant_id=str(principal.tenant_id),
        owner_tenant_id=str(owner_tenant_id),
    )
    raise NotFound(f"No {resource} matches that identifier.")
