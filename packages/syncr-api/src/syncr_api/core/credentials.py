"""Which credential a request presents, read from the request and nothing else.

Two kinds reach this api and the difference between them is not a preference. A browser presents
the ``syncr_session`` cookie, which is AMBIENT: the browser attaches it to a forged cross-origin
request as readily as to a real one, which is the whole reason CSRF protection exists. A bearer
client presents an ``Authorization`` header, which is not ambient: a hostile page cannot put a
header on a form post at all, and adding one through ``fetch`` makes the request non-simple, so the
browser preflights it and this deployment answers no CORS headers.

Three readers need that distinction and none of them may answer it differently, which is why it is
a value here rather than a condition inside one of them: the origin check asks whether there is
anything ambient to protect, the perimeter asks which resolver to use, and the pin path asks which
verdict surface to attribute a transition to.

**Presenting a bearer header is what makes a request a bearer request, whether or not the token
turns out to be good.** Deciding by the header rather than by the outcome keeps one reading for
every reader: a request that presents a token this deployment refuses is still a request that was
never a browser's, so it is answered as a bad token rather than falling back to a cookie.

This module reads headers and names values. It resolves nothing, so it holds no dependency on how
either credential is verified.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from starlette.requests import Request

    from syncr_api.core.principal import Principal

AUTHORIZATION_HEADER: Final = "authorization"

# The scheme RFC 6750 names, lowercased for comparison: RFC 7235 says a scheme is
# case-insensitive, and a client that sends `bearer` is not wrong.
BEARER_SCHEME: Final = "bearer"


class CredentialKind(StrEnum):
    """What one request presents to say who it is for."""

    # The browser's cookie. Ambient, so an unsafe request carrying it needs the origin check.
    SESSION = "session"
    # An access token in the `Authorization` header. Not ambient, and scoped to its grant.
    BEARER = "bearer"


def read_bearer_token(request: Request) -> str | None:
    """The access token this request presents, or ``None`` when it presents no bearer header."""
    header = request.headers.get(AUTHORIZATION_HEADER)
    if header is None:
        return None
    scheme, _, credential = header.partition(" ")
    if scheme.lower() != BEARER_SCHEME or not credential.strip():
        return None
    return credential.strip()


def presented_credential(request: Request) -> CredentialKind:
    """Which kind of credential this request presents.

    A request presenting neither reads as :attr:`CredentialKind.SESSION`, because the cookie is
    what this api asks a caller for by default: the refusal it then receives names the cookie and
    tells it to sign in, which is the useful answer for a browser and for anything that arrived
    without a credential by mistake.
    """
    if read_bearer_token(request) is not None:
        return CredentialKind.BEARER
    return CredentialKind.SESSION


class AccessTokenReader(Protocol):
    """The principal a presented access token authenticates, or the bearer refusal raised.

    Declared here rather than in the module that implements it so the perimeter that reads a
    reader off ``app.state`` names no type of the module that built the state: the two halves of
    the perimeter meet at this protocol and at nothing else.
    """

    def __call__(self, request: Request, transaction: AsyncSession) -> Principal: ...


# What a request that needs the Authorization Server's state says when the process that built
# the application never attached it. Named rather than generic, because the fix is one line in
# whichever process built the app.
OAUTH_STATE_NOT_ATTACHED: Final = (
    "app.state.oauth is not set, so this application has OAuth routes and no signing keys. "
    "Attach it with syncr_api.oauth.injection.build_oauth_state, the way the api entrypoint does."
)
