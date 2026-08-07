"""The consent routes' own dependency, which is the one thing here that needs a browser.

Separate from ``injection.py`` for a structural reason rather than a cosmetic one. The perimeter in
``accounts/injection.py`` has to reach the bearer resolution in ``injection.py``, because one
dependency accepts either credential and a route's shape must not depend on which credential its
caller holds. That import can only exist if ``injection.py`` reaches nothing in
``accounts/injection.py``, and the consent service was the one thing in it that did.

**The consent service resolves a BROWSER session and inherits the origin check with it.** A bearer
credential deliberately cannot reach these routes: a client holding an access token must not be able
to mint itself a fresh grant, because it could then widen its own scopes or outlive its own
revocation.

**Its repository is scoped by the session's tenant, resolved before the service exists.** So the
tenant it can reach is fixed by the credential rather than by anything in the request, and the
principal the service method takes is checked against that same answer.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# FastAPI resolves a dependency's annotations at RUNTIME to build the dependency graph, and a
# `type` alias is evaluated when it does, so every name reachable from an annotation below stays a
# runtime import: under TYPE_CHECKING it would resolve to a NameError while the app is being
# constructed.
from syncr_api.accounts.injection import PrincipalDep  # noqa: TC001
from syncr_api.accounts.repository import UserRepository
from syncr_api.core.clock import utc_now
from syncr_api.oauth.injection import TransactionDep  # noqa: TC001
from syncr_api.oauth.repository import OAuthRepository, PresentedCredentialRepository
from syncr_api.oauth.service import AuthorizationService


def get_authorization_service(
    transaction: TransactionDep, principal: PrincipalDep
) -> AuthorizationService:
    """The consent service, wired for this request and scoped to the signed-in tenant."""
    return AuthorizationService(
        clients=PresentedCredentialRepository(transaction),
        grants=OAuthRepository(transaction, principal.tenant_id),
        users=UserRepository(transaction),
        clock=utc_now,
    )


type AuthorizationServiceDep = Annotated[AuthorizationService, Depends(get_authorization_service)]
