"""What the SSE stream is defined against: its path, its channel, its intervals, its vocabulary.

The four event types are the whole set a client handles, and each names WHAT changed rather than
carrying the change: the client refetches on a terminal status, because pushing plan documents would
duplicate the read model over two transports.
"""

from __future__ import annotations

from typing import Final, Literal

from syncr_api.core.settings import API_PREFIX

# `/api/v1/events`, built from the versioned prefix rather than written out.
EVENTS_PREFIX: Final = f"{API_PREFIX}/events"

EVENTS_TAG: Final = "events"

# The Postgres channel every syncr process publishes to and every api process listens on. One
# channel rather than one per tenant, because a channel name cannot be parameterised in `LISTEN`
# without a statement per tenant: the tenant is on the payload and the hub fans out by it.
EVENT_CHANNEL: Final = "syncr_events"

type EventType = Literal["operation", "conflict", "projection", "notice"]
OPERATION: Final[EventType] = "operation"
CONFLICT: Final[EventType] = "conflict"
PROJECTION: Final[EventType] = "projection"
NOTICE: Final[EventType] = "notice"
EVENT_TYPES: Final = (OPERATION, CONFLICT, PROJECTION, NOTICE)

# How often a stream with nothing to say sends a comment. Short enough that a dead connection is
# detected inside a page's own patience, and long enough that an idle browser tab costs nothing. A
# proxy that closes an idle connection is the failure this exists to make visible.
HEARTBEAT_SECONDS: Final = 15.0

# How many undelivered events one connection holds before it is dropped. A client that has stopped
# reading is a client that has gone away: the alternative to dropping it is holding a growing queue
# for a socket nobody is on, and a client that reconnects refetches anyway.
SUBSCRIBER_BACKLOG: Final = 64

# Postgres refuses a notification payload of 8000 bytes or more. Every event here is identifiers and
# status, so this is a bound nothing approaches; it is stated so a payload that grew into a document
# is refused where it is published rather than at the driver.
PAYLOAD_LIMIT: Final = 4000
