"""The wire shapes the Google account routes exchange.

Two properties are stated in the field descriptions rather than only here, because a description
reaches the OpenAPI document and therefore the caller.

**The consent surface is data, not a page.** The api states the scopes, what each one lets syncr
do, and which calendars will be read; Settings renders that beside the button that opens
``authorizationUrl``. One statement of the scope set, in the package that owns the OAuth client.

**A connection carries its own notices.** The write-target expiry notice is raised at two volumes,
banner and a panel on Settings, so the shape is a list rather than a nullable single notice. An
empty list is the healthy state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from pydantic import Field

from syncr_api.core.notices import Notice  # noqa: TC001 - pydantic resolves annotations at runtime
from syncr_api.core.schemas import WireInstant, WireModel

if TYPE_CHECKING:
    from syncr_api.google_account.connect import GoogleConsent
    from syncr_api.google_account.service import GoogleConnection


class ScopeDisclosureResponse(WireModel):
    """One scope syncr requests, and what granting it lets syncr do."""

    scope: str
    statement: str = Field(
        description="What this scope lets syncr do, in the user's terms rather than Google's."
    )


class DisclosedCalendarResponse(WireModel):
    """One Google calendar already configured as a source, and whether it is read."""

    display_name: str
    included: bool


class GoogleConsentResponse(WireModel):
    """Everything the consent surface states, plus the URL that starts the flow."""

    authorization_url: str = Field(
        description=(
            "Google's consent URL for this deployment. Opening it is what starts the flow; it "
            "carries a signed state bound to this tenant and expires."
        )
    )
    scopes: list[ScopeDisclosureResponse]
    calendars_read: list[DisclosedCalendarResponse] = Field(
        description=(
            "The Google calendars already configured as sources. Empty on a first connect, "
            "because syncr has not seen the account yet."
        )
    )
    statement: str = Field(
        description="Which calendars syncr will read, stated for the account as it is now."
    )

    @classmethod
    def of(cls, surface: GoogleConsent) -> Self:
        """The wire shape of one consent surface."""
        return cls(
            authorization_url=surface.authorization_url,
            scopes=[
                ScopeDisclosureResponse(scope=disclosed.scope, statement=disclosed.statement)
                for disclosed in surface.scopes
            ],
            calendars_read=[
                DisclosedCalendarResponse(
                    display_name=calendar.display_name, included=calendar.included
                )
                for calendar in surface.calendars_read
            ],
            statement=surface.statement,
        )


class GoogleConnectionResponse(WireModel):
    """The state of the one Google account this tenant connected."""

    configured: bool = Field(
        description=(
            "Whether this deployment has a Google OAuth client at all. False means no connect is "
            "possible until an operator sets the credentials; ICS sources are unaffected."
        )
    )
    connected: bool
    granted_scopes: list[str] = Field(
        description="What Google says it granted, which can be narrower than what syncr asked for."
    )
    connected_at: WireInstant | None = None
    last_refresh_at: WireInstant | None = None
    notices: list[Notice] = Field(
        description=(
            "Every notice this connection's state raises. Write-target expiry raises two, a "
            "banner and a panel on Settings, because it is the loudest non-blocking condition in "
            "the product."
        )
    )

    @classmethod
    def of(cls, connection: GoogleConnection) -> Self:
        """The wire shape of the connection read model."""
        return cls(
            configured=connection.configured,
            connected=connection.connected,
            granted_scopes=list(connection.granted_scopes),
            connected_at=connection.connected_at,
            last_refresh_at=connection.last_refresh_at,
            notices=list(connection.notices),
        )
