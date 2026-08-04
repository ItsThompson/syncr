"""What the setup surface needs to list an account's calendars, declared by the caller.

One method, and it exists as a protocol for two reasons rather than one.

**The service must not know which provider answers.** Listing an account's calendars is a Google
question today, and the route that asks it is a calendar-source route: keeping the seam here means
the service states the rule (Google only) and the composition decides what fulfils it.

**A deployment with no Google credentials still serves the route.** The unconfigured reader answers
with the failure that names what is missing, so the surface reports a deployment state instead of a
502 from a request nobody could have made.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from syncr_api.calendars.google_client import GoogleReadFailed

if TYPE_CHECKING:
    from syncr_api.calendars.google_client import CalendarsAnswer

NOT_CONFIGURED_REASON: Final = (
    "This deployment has no Google OAuth client, so it cannot list an account's calendars. Set "
    "GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REDIRECT_URI and restart"
)


class RemoteCalendarReader(Protocol):
    """The calendars an account holds, or why they could not be read."""

    async def list_calendars(self) -> CalendarsAnswer:
        """Every calendar the connected account holds."""
        ...


@dataclass(frozen=True, slots=True)
class UnconfiguredCalendarReader:
    """The reader a deployment without Google credentials composes.

    Answers rather than raises, so the route's failure is the same shape whether Google refused the
    read or this deployment could never have made it.
    """

    async def list_calendars(self) -> CalendarsAnswer:
        return GoogleReadFailed(reason=NOT_CONFIGURED_REASON, attempts=0)
