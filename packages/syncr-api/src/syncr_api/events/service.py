"""``EventStreamService``: the one thing a stream request authorizes, on an explicit principal.

Thin, and it is a service rather than a function on the route for the reason every other read in
this application is: authorization is decided in the service layer, once, as the method's first act.
A stream is a read of everything that happens to one account, so the scope it needs is the same one
that reads a week.

It writes nothing and it reads no table. What it holds is the hub and the tenant boundary: the
frames it answers with are subscribed for one tenant, so a stream cannot be widened by anything in
the request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.core.principal import require_scope
from syncr_api.core.scopes import Scope
from syncr_api.events.streams import event_stream

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syncr_api.core.principal import Principal
    from syncr_api.events.hub import EventHub


class EventStreamService:
    """Opens one client's event stream, once their credential's scope allows it."""

    def __init__(self, hub: EventHub) -> None:
        self._hub = hub

    def open(self, principal: Principal) -> AsyncIterator[str]:
        """The frames this account's stream carries, for as long as the client stays connected.

        Not a coroutine: what it answers with is the generator the response streams, and awaiting
        the subscription here would register it before the response body began.
        """
        require_scope(principal, Scope.PLAN_READ)
        return event_stream(self._hub, principal.tenant_id)
