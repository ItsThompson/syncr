"""The token endpoint, from the client's side: exchange, refresh, and revoke.

Three RFC 6749 exchanges, form-encoded in and JSON out, against the endpoints discovery named.

**The refresh token rotates.** A refresh answers with a new one and the old one is dead the moment
it is presented, so the new one is stored and the old one discarded. Presenting a consumed refresh
token revokes the whole family, which is the Authorization Server's replay defense and is why a
client must never keep the one it just used.

**The access token is held in memory only.** It is a signed claim set with a fifteen-minute life
and it is never written anywhere.

**A failed refresh is not a generic failure.** It means the grant is gone, so it exits 3 with the
one instruction that fixes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Self

from syncr_cli.auth.discovery import CLIENT_ID
from syncr_cli.errors import ApiRefused, NotAuthenticated
from syncr_cli.exit_codes import ExitCode
from syncr_cli.wire.reading import integer, mapping, text

if TYPE_CHECKING:
    from syncr_cli.auth.discovery import AuthorizationServer
    from syncr_cli.http import Transport

GRANT_TYPE_AUTHORIZATION_CODE: Final = "authorization_code"
GRANT_TYPE_REFRESH_TOKEN: Final = "refresh_token"  # noqa: S105 - a grant type's name

TOKEN_DOCUMENT: Final = "token"  # noqa: S105 - the name of a response document, not a token

RE_AUTHORIZE = "Run 'syncr auth login' to authorize this machine again."


@dataclass(frozen=True, slots=True)
class TokenSet:
    """What one exchange handed back. The access token lives as long as this object does.

    **Neither token appears in this object's repr.** A default dataclass repr is a write waiting for
    its first caller: a test's assertion diff, an f-string in a future error message, or any log
    line. The module claims the access token is never written anywhere, and ``repr=False`` is what
    makes that a property of the type rather than of every caller's care.
    """

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int
    scopes: tuple[str, ...]

    @classmethod
    def read(cls, body: object) -> Self:
        payload = mapping(body, TOKEN_DOCUMENT)
        return cls(
            access_token=text(payload, "access_token", TOKEN_DOCUMENT),
            refresh_token=text(payload, "refresh_token", TOKEN_DOCUMENT),
            expires_in=integer(payload, "expires_in", TOKEN_DOCUMENT),
            scopes=tuple(text(payload, "scope", TOKEN_DOCUMENT).split()),
        )


def exchange_code(
    transport: Transport,
    server: AuthorizationServer,
    *,
    code: str,
    verifier: str,
    redirect_uri: str,
) -> TokenSet:
    """Trade the single-use code for a token pair, proving possession with the verifier.

    ``redirect_uri`` is sent again, as RFC 6749 section 4.1.3 requires: the server compares it
    with the one the code was issued against, so a code intercepted from one client cannot be
    redeemed against another's listener.
    """
    return TokenSet.read(
        transport.post_form(
            server.token_endpoint,
            {
                "grant_type": GRANT_TYPE_AUTHORIZATION_CODE,
                "client_id": CLIENT_ID,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            },
        )
    )


def refresh(transport: Transport, server: AuthorizationServer, *, refresh_token: str) -> TokenSet:
    """Trade a refresh token for a fresh pair, or say that authorization is needed again."""
    try:
        return TokenSet.read(
            transport.post_form(
                server.token_endpoint,
                {
                    "grant_type": GRANT_TYPE_REFRESH_TOKEN,
                    "client_id": CLIENT_ID,
                    "refresh_token": refresh_token,
                },
            )
        )
    except ApiRefused as refused:
        if refused.problem.exit_code is not ExitCode.NOT_AUTHENTICATED:
            raise
        raise NotAuthenticated(
            f"the stored authorization is no longer valid ({refused.problem.detail}) {RE_AUTHORIZE}"
        ) from refused


def revoke(transport: Transport, server: AuthorizationServer, *, refresh_token: str) -> None:
    """Revoke a refresh token and its family, server-side.

    Answering the same way whatever was presented is the endpoint's contract, so a token the
    server has never seen is not an error here either: what matters is that the grant is dead
    afterwards, and deleting a local file alone would leave it live.
    """
    transport.post_form_ignoring_body(
        server.revocation_endpoint,
        {"token": refresh_token, "client_id": CLIENT_ID},
    )
