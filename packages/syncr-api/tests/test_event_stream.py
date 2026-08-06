"""The SSE stream: what a connected client receives, and what the hub refuses to give it.

Driven through the generator rather than through a socket, because an SSE body never ends: a
request-response client blocks on it forever, which is why the read-never-writes walk names this
as the one endless read. The generator is the whole of the endpoint: the framing, the heartbeat, and
the subscription's lifetime. So this is where those are asserted, and the route's own two properties
(a session credential, and no bearer) are asserted against the source and the app.

Four groups.

**The frames.** A named event type, one data line, and a blank line. The data is one line because a
newline inside it would split the frame.

**The tenant boundary.** Two clients on one process receive their own account's events and nothing
else, which is the property a shared hub could silently lose.

**The heartbeat.** A comment rather than an event, sent when the window passes with nothing to say,
so a dead connection is detectable and a client's own handler never fires for it.

**What is refused.** A payload that grew into a document does not fit a notification and is refused
where it is published; a client that stopped reading is dropped rather than waited for; and a solve
that finished before the stream opened is not replayed, because there is no buffer and the client
refetches.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

import syncr_api.solving.runner  # noqa: F401  - imported so its own families are registered
from syncr_api.core.settings import API_PREFIX
from syncr_api.events.config import EVENT_TYPES, HEARTBEAT_SECONDS, SUBSCRIBER_BACKLOG
from syncr_api.events.envelopes import (
    HEARTBEAT_FRAME,
    EventTooLarge,
    ServerEvent,
    as_frame,
    as_payload,
    event_of_payload,
    operation_event,
)
from syncr_api.events.hub import EventHub
from syncr_api.events.streams import event_stream
from syncr_api.solving.config import (
    OPERATION_KINDS,
    PENDING,
    SOLVE,
    SUCCEEDED,
    TERMINAL_STATUSES,
)
from syncr_api.solving.records import OperationRecord
from syncr_common.metrics import REGISTRY
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

WEEK = IsoWeek(2026, 7)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

A_TENANT = uuid4()
ANOTHER_TENANT = uuid4()


def an_operation(tenant_id: object = None, **overrides: object) -> OperationRecord:
    """One operation record, as a repository answers with one."""
    fields: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": tenant_id or A_TENANT,
        "kind": SOLVE,
        "status": PENDING,
        "iso_week": WEEK,
        "source_id": None,
        "input_version": None,
        "candidate_adjustment": None,
        "scheduled_for": NOW,
        "started_at": None,
        "finished_at": None,
        "result_revision_id": None,
        "superseded_by": None,
        "attempt": 1,
        "error_code": None,
        "error_message": None,
    }
    return OperationRecord(**(fields | overrides))  # type: ignore[arg-type]


async def frames(stream: AsyncIterator[str], count: int) -> list[str]:
    """The first ``count`` frames, with a bound so a hung generator fails rather than hangs."""
    read: list[str] = []
    for _ in range(count):
        read.append(await asyncio.wait_for(anext(stream), timeout=2.0))
    return read


class TestTheFrames:
    def test_a_frame_names_its_type_and_holds_one_data_line(self) -> None:
        frame = as_frame(operation_event(an_operation()))
        lines = frame.split("\n")

        assert lines[0] == "event: operation"
        assert lines[1].startswith("data: ")
        assert lines[2:] == ["", ""]

    def test_the_data_is_the_same_json_the_http_route_answers_with(self) -> None:
        # So a client needs no second type for the pushed form of a resource it already reads.
        operation = an_operation(status=SUCCEEDED)

        data = operation_event(operation).data

        assert data["id"] == str(operation.id)
        assert data["status"] == SUCCEEDED
        assert data["target"] == {"isoWeek": str(WEEK), "sourceId": None}

    def test_an_event_carries_no_plan_document(self) -> None:
        """The rule, from the side that can fail: the schema has no field to carry one.

        Asserted over the operation event because it is the one an adoption publishes, and the
        document is what an adoption wrote. A field added to the schema that carried one would show
        up here as a key nothing in the vocabulary names.
        """
        data = operation_event(an_operation()).data

        assert "document" not in data
        assert "blocks" not in data
        assert "failedInputSnapshot" not in data

    def test_a_payload_round_trips_across_the_channel(self) -> None:
        # A notification is a boundary between processes, so a payload that could be written and not
        # read would fail on whichever process happened to be the reader.
        event = operation_event(an_operation())

        assert event_of_payload(as_payload(event)) == event

    def test_a_payload_that_grew_into_a_document_is_refused_where_it_is_published(self) -> None:
        # The structural half of "events carry no documents": one would not fit a notification, so
        # the refusal is at the publish rather than at the driver.
        oversized = ServerEvent(type="operation", tenant_id=A_TENANT, data={"blocks": "x" * 5000})

        with pytest.raises(EventTooLarge):
            as_payload(oversized)


class TestTheTenantBoundary:
    async def test_a_client_receives_its_own_account_events(self) -> None:
        hub = EventHub()
        stream = event_stream(hub, A_TENANT, frames=2)
        assert await frames(stream, 1) == [HEARTBEAT_FRAME]
        operation = an_operation()

        hub.publish(operation_event(operation))

        assert await frames(stream, 1) == [as_frame(operation_event(operation))]

    async def test_two_clients_on_one_process_see_only_their_own(self) -> None:
        hub = EventHub()
        mine = event_stream(hub, A_TENANT, frames=2)
        theirs = event_stream(hub, ANOTHER_TENANT, frames=2)
        await frames(mine, 1)
        await frames(theirs, 1)

        delivered = hub.publish(operation_event(an_operation(A_TENANT)))

        assert delivered == 1
        assert "event: operation" in (await frames(mine, 1))[0]

    async def test_a_client_that_disappears_leaves_no_subscription_behind(self) -> None:
        """Starlette cancels an abandoned generator, which raises through the hub's own yield."""
        hub = EventHub()
        stream: AsyncGenerator[str, None] = event_stream(hub, A_TENANT)
        await frames(stream, 1)
        assert hub.connections == 1

        await stream.aclose()

        assert hub.connections == 0
        assert REGISTRY.get_sample_value("syncr_sse_connections") == 0.0


class TestTheHeartbeat:
    async def test_a_window_with_nothing_to_say_sends_a_comment(self) -> None:
        hub = EventHub()

        read = await frames(event_stream(hub, A_TENANT, heartbeat_seconds=0.01, frames=3), 3)

        assert read == [HEARTBEAT_FRAME] * 3

    def test_the_heartbeat_is_a_comment_rather_than_one_of_the_four_types(self) -> None:
        # So a client's own handler never fires for it and nothing has to filter heartbeats out.
        assert HEARTBEAT_FRAME.startswith(":")
        assert not any(f"event: {one}" in HEARTBEAT_FRAME for one in EVENT_TYPES)

    def test_the_interval_is_shorter_than_an_idle_proxy_timeout(self) -> None:
        # A proxy closing an idle connection is the failure the heartbeat exists to make visible,
        # and sixty seconds is the shortest such timeout in ordinary use.
        assert HEARTBEAT_SECONDS < 60


class TestWhatIsNotDelivered:
    async def test_an_event_published_before_the_stream_opened_is_not_replayed(self) -> None:
        """No replay buffer in P0: a reconnecting client refetches, which is the source of truth.

        A buffer would be per client and bounded, which is a second delivery mechanism for a problem
        one refetch already solves.
        """
        hub = EventHub()
        assert hub.publish(operation_event(an_operation())) == 0

        read = await frames(event_stream(hub, A_TENANT, heartbeat_seconds=0.01, frames=2), 2)

        assert read == [HEARTBEAT_FRAME] * 2

    async def test_a_client_that_stopped_reading_is_dropped_rather_than_waited_for(self) -> None:
        # The alternative is a growing queue for a socket nobody is on, and a client that reconnects
        # refetches anyway.
        hub = EventHub()
        before = REGISTRY.get_sample_value("syncr_sse_events_dropped_total") or 0.0
        async with hub.subscribe(A_TENANT):
            for _ in range(SUBSCRIBER_BACKLOG + 2):
                hub.publish(operation_event(an_operation()))

        dropped = REGISTRY.get_sample_value("syncr_sse_events_dropped_total") or 0.0
        assert dropped == before + 2.0

    def test_publishing_to_nobody_is_not_an_error(self) -> None:
        # The ordinary state: nobody has a tab open.
        assert EventHub().publish(operation_event(an_operation())) == 0


class TestTheRoute:
    def test_the_stream_is_the_one_endless_read_and_it_is_under_the_api_prefix(self) -> None:
        from syncr_api.events.config import EVENTS_PREFIX

        assert f"{API_PREFIX}/events" == EVENTS_PREFIX

    def test_the_route_module_cannot_reach_the_bearer_credential(self) -> None:
        """Session cookie only, asserted against the source rather than against today's wiring.

        The accounts dependency reads the cookie and nothing else, so declaring it IS the rule; what
        this adds is that a later widening of that dependency cannot widen the stream with it.
        """
        from pathlib import Path

        import syncr_api.events.api as route_module

        body = Path(route_module.__file__ or "").read_text(encoding="utf-8")

        assert "BearerPrincipalDep" not in body
        assert "require_bearer_principal" not in body
        assert "PrincipalDep" in body

    def test_the_stream_service_holds_no_session_so_the_route_cannot_write(self) -> None:
        """Which is the real reason excluding this route from the read-never-writes walk is safe.

        The walk cannot drive an endless body, so the exclusion rests on a property rather than on a
        promise: the service takes the hub and nothing else, so there is no session for it to write
        through and no repository it could compose one from.
        """
        import inspect

        from syncr_api.events.service import EventStreamService

        taken = inspect.signature(EventStreamService.__init__).parameters

        assert list(taken) == ["self", "hub"]


class TestEveryFamilyThisSliceExportsIsVisibleBeforeItIsUsed:
    """The reading "nothing is stuck" and the reading "nobody has looked yet" have to differ.

    A labeled Prometheus family does not exist until a label is used, so an alert stated over one is
    silent until the first observation. This epic has shipped that twice: a counter that incremented
    before its document existed, and a gauge that could not fire for a duty failing every pass. So
    every family added here is read out of the exposition as a scraper reads it, on a process that
    has done no work.
    """

    @pytest.mark.parametrize(
        "family",
        [
            "syncr_sse_connections",
            "syncr_sse_events_dropped_total",
            "syncr_sse_listener_reconnects_total",
            "syncr_solve_claim_races_lost_total",
            "syncr_solve_tenant_failures_total",
            "syncr_solve_superseded_ratio",
        ],
        ids=lambda one: one,
    )
    def test_an_unlabeled_family_is_in_the_exposition(self, family: str) -> None:
        assert REGISTRY.get_sample_value(family) is not None

    @pytest.mark.parametrize("kind", list(OPERATION_KINDS), ids=lambda one: one)
    def test_every_operation_kind_is_a_label_on_both_kind_labeled_families(self, kind: str) -> None:
        # Seeded at import rather than on the first pass, so a worker that has not ticked yet is
        # distinguishable from one whose queues are empty. Presence rather than zero, because a
        # sibling test in this process may legitimately have observed one already.
        assert (
            REGISTRY.get_sample_value("syncr_operations_non_terminal", {"kind": kind}) is not None
        )
        assert (
            REGISTRY.get_sample_value("syncr_operation_queue_delay_seconds_count", {"kind": kind})
            is not None
        )

    @pytest.mark.parametrize("outcome", list(TERMINAL_STATUSES), ids=lambda one: one)
    def test_every_terminal_status_is_a_label_on_the_solve_counter(self, outcome: str) -> None:
        assert REGISTRY.get_sample_value("syncr_solve_total", {"outcome": outcome}) is not None
