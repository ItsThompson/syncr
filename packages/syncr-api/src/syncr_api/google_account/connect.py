"""The consent surface: what syncr states before it sends the user to Google.

Google's consent screen names the scopes in Google's vocabulary and says nothing about which
calendars syncr will read, because it cannot: the read scope reaches every calendar in the
account, and what confines it is syncr's own include-or-exclude choice. So the surface built here
carries both, and the connect flow is two acts rather than one: connect the account, then choose
the calendars.

**The disclosure is the response to the connect request, not a page.** The api states the scopes,
their plain meaning, and which calendars will be read; the Settings screen renders it beside the
button that opens the returned URL. That keeps one statement of the scope set, in the package
that owns the OAuth client, rather than a copy in the frontend that drifts from the runbook.

**Which calendars will be read is answered honestly in both cases.** With Google sources already
configured it is the list of them, marked by whether each is included. With none, which is the
first connect, it is the statement that nothing is read until the user includes it.

**An unconfigured deployment says so.** With no client id there is nothing to redirect to, and a
connect attempt that produced a broken Google URL would look like Google refusing syncr.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from syncr_api.google_account.config import (
    AUTHORIZATION_ENDPOINT,
    FORCE_CONSENT,
    NOTHING_IS_READ_YET,
    OFFLINE_ACCESS,
    REQUESTED_SCOPES,
    RESPONSE_TYPE_CODE,
    SCOPE_SEPARATOR,
    SCOPE_STATEMENTS,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.calendars.records import CalendarSourceRecord


@dataclass(frozen=True, slots=True)
class ScopeDisclosure:
    """One scope, and what granting it lets syncr do, in the user's terms."""

    scope: str
    statement: str


@dataclass(frozen=True, slots=True)
class CalendarDisclosure:
    """One calendar the account already holds as a source, and whether it is read."""

    display_name: str
    included: bool


@dataclass(frozen=True, slots=True)
class GoogleConsent:
    """Everything the consent surface states, plus the URL that starts the flow."""

    authorization_url: str
    scopes: tuple[ScopeDisclosure, ...]
    calendars_read: tuple[CalendarDisclosure, ...]
    statement: str


def consent_surface(
    *, client_id: str, redirect_uri: str, state: str, sources: Sequence[CalendarSourceRecord]
) -> GoogleConsent:
    """The scopes, the calendars, and the authorization URL for one connect attempt."""
    return GoogleConsent(
        authorization_url=authorization_url(
            client_id=client_id, redirect_uri=redirect_uri, state=state
        ),
        scopes=tuple(
            ScopeDisclosure(scope=scope, statement=SCOPE_STATEMENTS[scope])
            for scope in REQUESTED_SCOPES
        ),
        calendars_read=tuple(
            CalendarDisclosure(display_name=source.display_name, included=source.included)
            for source in sources
        ),
        statement=_what_will_be_read(sources),
    )


def authorization_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """Google's consent URL for this client, this redirect, and this flow.

    ``access_type=offline`` is what makes Google issue a refresh token at all, and
    ``prompt=consent`` is what makes it issue a NEW one every time. Without the second, a
    reconnect of an account that already granted these scopes returns an access token and no
    refresh token, so the reconnect offered to repair a dead credential would store nothing and
    the notice would still be there afterwards.
    """
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": RESPONSE_TYPE_CODE,
            "scope": SCOPE_SEPARATOR.join(REQUESTED_SCOPES),
            "access_type": OFFLINE_ACCESS,
            "prompt": FORCE_CONSENT,
            "state": state,
        }
    )
    return f"{AUTHORIZATION_ENDPOINT}?{query}"


def _what_will_be_read(sources: Sequence[CalendarSourceRecord]) -> str:
    """The sentence that answers "which of my calendars does this read".

    Stated from the sources that exist rather than from the scope, because the scope's answer is
    "all of them" and syncr's answer is "the ones you included".
    """
    included = [source.display_name for source in sources if source.included]
    if not sources:
        return NOTHING_IS_READ_YET
    if not included:
        return (
            "No Google calendar is included right now, so connecting reads none of them. Include "
            "one in Settings and it becomes an anchor source on the next sync."
        )
    return (
        f"syncr reads {len(included)} of the {len(sources)} Google calendars configured as "
        "sources, listed below. The rest are excluded and are never read."
    )
