"""The product's routes, as this client calls them.

One method per read rather than one generic ``get``, so each is independently substitutable in a
test with a single return shape and no conditional inside a stub. The bearer credential is
attached by the session, which obtains it lazily: a command that never calls a method here never
refreshes a token.

``/api/v1`` is stated here because discovery does not carry it. The versioned prefix is the
resource server, which is exactly what an access token's audience names, so the constant and the
``aud`` claim are the same string and a mismatch shows up as a rejected token rather than as a
404.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_cli.http import Transport

API_PREFIX: Final = "/api/v1"


class Credential(Protocol):
    """What a request presents. Satisfied by :class:`~syncr_cli.auth.session.Session`.

    A protocol rather than the class, so this module depends on the one thing it uses -- a header
    -- and not on how that header is obtained. It also means nothing here can reach into a session
    and refresh it out of turn.
    """

    def headers(self) -> dict[str, str]:
        """The ``Authorization`` header a request carries."""
        ...


class ApiClient:
    """The syncr API, as the commands in this package use it."""

    def __init__(self, *, transport: Transport, api_url: str, session: Credential) -> None:
        self._transport = transport
        self._api_url = api_url
        self._session = session

    def read_week(self, iso_week: str) -> Any:
        """The composed week view: the plan, or the reason there is none."""
        return self._get(f"/weeks/{iso_week}")

    def list_areas(self) -> Any:
        """Every Area this tenant has declared, which is how the ledger names one."""
        return self._get("/areas")

    def read_operation(self, operation_id: str) -> Any:
        """One tracked long-running job, as a wait polls it."""
        return self._get(f"/operations/{operation_id}")

    def _get(self, path: str) -> Any:
        return self._transport.get(f"{self._api_url}{API_PREFIX}{path}", headers=self._headers())

    def _headers(self) -> Mapping[str, str]:
        return self._session.headers()
