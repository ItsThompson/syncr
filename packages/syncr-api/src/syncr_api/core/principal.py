"""The principal, and the two authorization checks every service calls.

The principal is who the request is for and what they may do. It is resolved once, at
the HTTP edge, from whichever credential the caller presented, and then passed
explicitly into every service method. An ambient principal read from a context variable
is how a new caller silently skips authorization, so there is no such context variable
to read.

The scopes travel ON the principal rather than beside it. A service method handed a
subject without its authority can authorize the tenant and forget the capability, and
that omission compiles; carrying both in one value means the one argument every service
takes is the whole answer to "may this request do this".

:func:`authorize_tenant` raises :class:`~syncr_api.core.errors.NotFound`, never
``Forbidden``. A 403 on someone else's row confirms the row exists, which is a
disclosure in itself; a 404 says only that the caller has nothing by that identifier.
:func:`require_scope` does raise ``Forbidden``, because a scope answer discloses nothing:
the caller already knows which capabilities exist, and being told the credential is too
narrow is what lets them re-authorize instead of guessing.

Both denials are logged, because the wire deliberately says little and the log is
therefore the only place a probing caller becomes visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.core.errors import Forbidden, NotFound
from syncr_api.core.scopes import format_scopes
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from syncr_api.core.scopes import Scope
    from syncr_domain.identifiers import TenantId, UserId

_log = get_logger("syncr.authz")


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated subject of one request, and the authority it was granted.

    A tenant holds exactly one user permanently, so the first two are not independent
    coordinates: the pair travels together because authentication resolves a subject
    while authorization resolves a scope, and the two answers are wanted at
    different layers.

    ``scopes`` has no default. A browser session carries
    :data:`~syncr_api.core.scopes.ALL_SCOPES` because the user is acting directly, and a
    bearer token carries only what its grant was issued for; a defaulted field is how a
    third credential type would acquire one of those two answers without choosing it.
    """

    tenant_id: TenantId
    user_id: UserId
    scopes: frozenset[Scope]

    def carries(self, scope: Scope) -> bool:
        """True when this credential was issued the authority ``scope`` names."""
        return scope in self.scopes


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


def require_scope(principal: Principal, scope: Scope) -> None:
    """Raise :class:`Forbidden` unless the principal's credential carries ``scope``.

    Called once per service method, as its first act, alongside
    :func:`authorize_tenant`. Not from a route, because a route is not where
    authorization lives, and not from a helper the method happens to reach, because a
    second caller of that helper is how a path ends up unchecked.
    """
    if principal.carries(scope):
        return
    held = format_scopes(principal.scopes)
    _log.warning(
        "authz.scope.denied",
        required_scope=scope.value,
        held_scopes=held,
        tenant_id=str(principal.tenant_id),
    )
    raise Forbidden(
        f"This credential carries {held or 'no scopes'}, not {scope.value}, so the "
        "request was not applied. Nothing was changed. Anything within the scopes it "
        "does carry still works; re-authorize to widen them."
    )
