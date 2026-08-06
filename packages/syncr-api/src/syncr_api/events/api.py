"""The one route: an open stream, four event types, and a comment when nothing has happened.

Thin, like every other route module. What it holds that a normal route does not is the generator: an
SSE response is a body that never ends, so the handler answers with the stream and the framing lives
in ``envelopes.py``.

**The session cookie is the only credential.** The route declares the accounts dependency, which
reads the cookie and nothing else, so a bearer token cannot open a stream: the CLI polls the
operation resource instead, and bearer support here would be surface nothing uses. This module
deliberately does not import the bearer dependency, and a test reads that from the source.

**A client that disappears leaves nothing behind.** Starlette cancels an abandoned generator, which
raises through the ``yield`` inside the hub's subscription, and the subscription unregisters on the
way out.
"""

from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.events.injection import EventStreamServiceDep

router = APIRouter()

SSE_MEDIA_TYPE = "text/event-stream"

# Told to any proxy in front of the api. Buffering an SSE body defeats it entirely: the client would
# receive the whole stream when the connection closed.
_STREAM_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


@router.get(
    "",
    summary="The event stream. Session credential only, and it carries no plan documents",
    response_class=StreamingResponse,
)
async def stream_events(
    principal: PrincipalDep, service: EventStreamServiceDep
) -> StreamingResponse:
    """Every operation, conflict, projection and notice of this account, as they happen."""
    return StreamingResponse(
        service.open(principal), media_type=SSE_MEDIA_TYPE, headers=_STREAM_HEADERS
    )
