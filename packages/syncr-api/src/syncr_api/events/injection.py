"""The dependencies the events route declares.

The hub is process-wide state on ``app.state.events``, attached by the factory exactly as the
settings are: one fan-out per process, because the streams it fans out to are that process's own
sockets. A request-scoped hub would be a hub with one subscriber and no publisher.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from syncr_api.events.hub import EventHub
from syncr_api.events.service import EventStreamService


def get_event_hub(request: Request) -> EventHub:
    """This process's event hub."""
    hub: EventHub = request.app.state.events
    return hub


type EventHubDep = Annotated[EventHub, Depends(get_event_hub)]


def get_event_stream_service(hub: EventHubDep) -> EventStreamService:
    """The stream service, over this process's hub."""
    return EventStreamService(hub)


type EventStreamServiceDep = Annotated[EventStreamService, Depends(get_event_stream_service)]
