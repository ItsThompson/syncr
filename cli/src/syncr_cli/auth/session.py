"""The credential for one invocation: an access token in memory, refreshed from the store.

**In memory only, for one process.** An access token is a signed claim set with a fifteen-minute
life, so a command holds one for as long as it runs and writes it nowhere.

**The refresh rotates and the new token is stored immediately.** The Authorization Server
consumes the presented refresh token and issues a successor, and presenting a consumed one
revokes the whole family. So the successor is written before it is used: a process that refreshed
and then crashed must not leave the store holding a token the server has already retired.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_cli.auth.claims import TokenClaims
from syncr_cli.auth.tokens import RE_AUTHORIZE, refresh
from syncr_cli.errors import NotAuthenticated

if TYPE_CHECKING:
    from syncr_cli.auth.discovery import AuthorizationServer
    from syncr_cli.auth.storage import RefreshTokenStore
    from syncr_cli.auth.tokens import TokenSet
    from syncr_cli.http import Transport

AUTHORIZATION_HEADER = "Authorization"
BEARER_SCHEME = "Bearer"


class Session:
    """The bearer credential a command presents, obtained lazily and at most once.

    Lazily, because a command that answers from its arguments needs no credential, and at most
    once, because a refresh consumes the stored token: two refreshes in one process would present
    the successor's predecessor and look exactly like a replay.
    """

    def __init__(
        self,
        *,
        transport: Transport,
        server: AuthorizationServer,
        store: RefreshTokenStore,
    ) -> None:
        self._transport = transport
        self._server = server
        self._store = store
        self._tokens: TokenSet | None = None

    def adopt(self, tokens: TokenSet) -> None:
        """Hold the pair a completed authorization produced, and store its refresh token."""
        self._store.write(tokens.refresh_token)
        self._tokens = tokens

    @property
    def tokens(self) -> TokenSet:
        """The token pair for this invocation, refreshing the stored grant if needed."""
        if self._tokens is None:
            self._tokens = self._refreshed()
        return self._tokens

    @property
    def claims(self) -> TokenClaims:
        """Who this invocation is authenticated as, read from the access token it holds."""
        return TokenClaims.of(self.tokens.access_token)

    def headers(self) -> dict[str, str]:
        """The ``Authorization`` header a request to the api carries."""
        return {AUTHORIZATION_HEADER: f"{BEARER_SCHEME} {self.tokens.access_token}"}

    def _refreshed(self) -> TokenSet:
        stored = self._store.read()
        if stored is None:
            raise NotAuthenticated(
                f"this machine holds no authorization for the API. {RE_AUTHORIZE}"
            )
        tokens = refresh(self._transport, self._server, refresh_token=stored)
        self._store.write(tokens.refresh_token)
        return tokens
