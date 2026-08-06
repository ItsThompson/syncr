"""What one event carries, how it crosses the channel, and what the wire holds.

**An event carries status and identifiers, never a plan document.** So each builder below dumps a
wire model that already exists -- the operation resource, the conflict resource, the
reconciliation's
own tally, the degradation notice -- rather than composing a payload of its own. The client then
needs no second type for the pushed form of a resource it already reads over HTTP, and "no document
reaches the stream" is a property of those four schemas rather than a rule this module has to
enforce a second time.

``PAYLOAD_LIMIT`` is what makes that structural rather than asserted: a payload holding a week's
blocks would not fit, and it is refused where it is published.

**The tenant is on the envelope and not in the data.** A subscriber is fanned out to by tenant, so
the routing key has to survive the trip; the data is what the client sees, and it already knows
whose
account it is looking at.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_api.conflicts.schemas import ConflictResponse
from syncr_api.events.config import CONFLICT, NOTICE, OPERATION, PAYLOAD_LIMIT, PROJECTION
from syncr_api.solving.schemas import OperationResponse

if TYPE_CHECKING:
    from syncr_api.calendars.projection import ReconcileResult
    from syncr_api.core.columns import JsonObject
    from syncr_api.core.notices import Notice
    from syncr_api.events.config import EventType
    from syncr_api.plans.records import ConflictRecord
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek

TYPE = "type"
TENANT = "tenant"
DATA = "data"

# What an idle stream sends. A comment rather than an event, so a client's `onmessage` never fires
# for it and nothing has to filter heartbeats out of the four real types.
HEARTBEAT_FRAME: Final = ": heartbeat\n\n"


class EventTooLarge(Exception):
    """An event's payload exceeds what a notification carries, which a document would."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ServerEvent:
    """One thing that changed, addressed to one tenant."""

    type: EventType
    tenant_id: TenantId
    data: JsonObject


def operation_event(operation: OperationRecord) -> ServerEvent:
    """An operation reached a new status. The client refetches on a terminal one."""
    return ServerEvent(
        type=OPERATION,
        tenant_id=operation.tenant_id,
        data=_dumped(OperationResponse.of(operation)),
    )


def conflict_event(conflict: ConflictRecord) -> ServerEvent:
    """A commitment landed on a planned block. The one event that raises a notification."""
    return ServerEvent(
        type=CONFLICT, tenant_id=conflict.tenant_id, data=_dumped(ConflictResponse.of(conflict))
    )


def projection_event(
    tenant_id: TenantId, iso_week: IsoWeek, result: ReconcileResult
) -> ServerEvent:
    """A week was written out to the calendar, and what that reconciliation did."""
    return ServerEvent(
        type=PROJECTION,
        tenant_id=tenant_id,
        data={
            "isoWeek": str(iso_week),
            "result": {
                "inserted": result.inserted,
                "patched": result.patched,
                "deleted": result.deleted,
                "foreignDeleted": result.foreign_deleted,
                "unchanged": result.unchanged,
                "durationMs": result.duration_ms,
            },
        },
    )


def notice_event(tenant_id: TenantId, notice: Notice) -> ServerEvent:
    """Something is degraded, at a stated volume, naming what still works."""
    return ServerEvent(type=NOTICE, tenant_id=tenant_id, data=_dumped(notice))


def as_payload(event: ServerEvent) -> str:
    """The event as the text one notification carries, or a refusal because it is too large."""
    payload = json.dumps(
        {TYPE: event.type, TENANT: str(event.tenant_id), DATA: event.data},
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(payload.encode()) > PAYLOAD_LIMIT:
        raise EventTooLarge(
            f"a {event.type} event serialises to {len(payload)} characters, over the "
            f"{PAYLOAD_LIMIT} one notification carries: an event states what changed and the "
            "client refetches it, so a payload this size is a document that should not be pushed"
        )
    return payload


def event_of_payload(payload: str) -> ServerEvent:
    """The event a notification's text names.

    Both halves are here so the pair round-trips. The channel is a boundary between processes and a
    payload that could be written and not read would fail on whichever process happened to be the
    reader.
    """
    read = json.loads(payload)
    return ServerEvent(type=read[TYPE], tenant_id=UUID(read[TENANT]), data=read[DATA])


def as_frame(event: ServerEvent) -> str:
    """The event as one SSE frame: a named type, one data line, and a blank line.

    The data is one line because a newline inside it would split the frame, and ``json.dumps``
    escapes every newline a value could hold.
    """
    return f"event: {event.type}\ndata: {json.dumps(event.data, separators=(',', ':'))}\n\n"


def _dumped(model: OperationResponse | ConflictResponse | Notice) -> JsonObject:
    """One wire model as the JSON a client reads, aliased exactly as its HTTP response is."""
    return dict(model.model_dump(mode="json", by_alias=True))
