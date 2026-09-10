"""Reconcile syncr's write-target Google calendar against a projection.

This adapter refuses before it reads when writes are unavailable. Once writes begin, a provider
failure raises with the exact work that landed, so a partial reconciliation never reads as success.
"""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import TYPE_CHECKING

from syncr_api.calendars.google_client import EventsRead, GoogleCalendarClient
from syncr_api.calendars.google_config import WRITE_DEADLINE_SECONDS
from syncr_api.calendars.google_events import SYNCR_KEY_PROPERTY, WriteRefused, WritesUnavailable
from syncr_api.calendars.google_values import ReadSpan, read_span
from syncr_api.calendars.projection import ProjectionAction, ReconcileResult
from syncr_api.calendars.projection_errors import ProjectionFailed, ProjectionRefused
from syncr_api.calendars.reconciliation import ExistingEvent, plan_reconciliation
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from syncr_api.calendars.google_events import EventWriting, GoogleEventWriter, WriteAnswer
    from syncr_api.calendars.google_payloads import GoogleEventPayload
    from syncr_api.calendars.projection import ProjectedEvent
    from syncr_api.calendars.reconciliation import ReconciliationPlan
    from syncr_api.calendars.records import CalendarSourceRecord
    from syncr_domain.intervals import Interval
    from syncr_domain.zones import ZoneProfile

_log = get_logger("syncr.calendars")


class GoogleWriteTargetAdapter:
    """Overwrite one Google write target over its horizon, or raise with its partial result.

    Refusal means the deployment cannot write and no provider call occurs. Failure means work may
    have landed and carries counts for repair or retry decisions.
    """

    def __init__(
        self,
        *,
        client: GoogleCalendarClient,
        profile: ZoneProfile,
        horizon: Interval,
        writes: EventWriting,
        write_deadline_seconds: float = WRITE_DEADLINE_SECONDS,
    ) -> None:
        self._client = client
        self._profile = profile
        self._horizon = horizon
        self._writes = writes
        self._write_deadline = write_deadline_seconds

    async def reconcile(
        self, target: CalendarSourceRecord, desired: list[ProjectedEvent]
    ) -> ReconcileResult:
        """Make the target match desired events or raise with the writes that already landed."""
        if isinstance(self._writes, WritesUnavailable):
            raise ProjectionRefused(self._writes.reason)
        started = perf_counter()
        identity = _identity(target)
        plan = plan_reconciliation(desired, await self._existing(target))
        _log.info(
            "calendars.projection.planned",
            **identity,
            desired_count=len(desired),
            **plan.as_log_fields(),
        )
        result = await self._applied(target, plan, writer=self._writes, started=started)
        _log.info("calendars.projection.reconciled", **identity, **result.as_log_fields())
        return result

    async def _existing(self, target: CalendarSourceRecord) -> list[ExistingEvent]:
        answer = await self._client.list_events(
            target.external_id, sync_token=None, window=self._horizon
        )
        if not isinstance(answer, EventsRead):
            raise ProjectionFailed(
                "the calendar syncr writes to could not be read, so the plan was not written: "
                f"{_reason_of(answer)}."
            )
        return [
            _as_existing_event(payload, profile=self._profile)
            for payload in answer.events
            if not payload.is_cancelled
        ]

    async def _applied(
        self,
        target: CalendarSourceRecord,
        plan: ReconciliationPlan,
        *,
        writer: GoogleEventWriter,
        started: float,
    ) -> ReconcileResult:
        counts = dict.fromkeys(ProjectionAction, 0)
        try:
            async with asyncio.timeout(self._write_deadline):
                await self._sent(plan, counts, writer=writer, target=target, started=started)
        except TimeoutError:
            raise ProjectionFailed(
                f"the reconciliation was stopped after {self._write_deadline:.0f}s without "
                "finishing, so part of the plan reached the calendar and part did not.",
                applied=_result(counts, plan, started),
            ) from None
        return _result(counts, plan, started)

    async def _sent(
        self,
        plan: ReconciliationPlan,
        counts: dict[ProjectionAction, int],
        *,
        writer: GoogleEventWriter,
        target: CalendarSourceRecord,
        started: float,
    ) -> None:
        calendar_id = target.external_id
        for patch in plan.patches:
            await self._one(
                writer.patch(calendar_id, patch.event_id, patch.intended),
                counts,
                ProjectionAction.PATCHED,
                plan,
                started,
            )
        for insert in plan.inserts:
            await self._one(
                writer.insert(calendar_id, insert),
                counts,
                ProjectionAction.INSERTED,
                plan,
                started,
            )
        for removal in plan.deletes:
            await self._one(
                writer.delete(calendar_id, removal.event_id),
                counts,
                ProjectionAction.FOREIGN_DELETED if removal.foreign else ProjectionAction.DELETED,
                plan,
                started,
            )

    async def _one(
        self,
        write: Awaitable[WriteAnswer],
        counts: dict[ProjectionAction, int],
        action: ProjectionAction,
        plan: ReconciliationPlan,
        started: float,
    ) -> None:
        answer = await write
        if isinstance(answer, WriteRefused):
            raise ProjectionFailed(answer.reason, applied=_result(counts, plan, started))
        counts[action] += 1


def _identity(source: CalendarSourceRecord) -> dict[str, str]:
    return {"source_id": str(source.id), "tenant_id": str(source.tenant_id)}


def _reason_of(answer: object) -> str:
    return getattr(answer, "reason", "Google returned an unreadable answer")


def _result(
    counts: dict[ProjectionAction, int], plan: ReconciliationPlan, started: float
) -> ReconcileResult:
    return ReconcileResult(
        inserted=counts[ProjectionAction.INSERTED],
        patched=counts[ProjectionAction.PATCHED],
        deleted=counts[ProjectionAction.DELETED],
        foreign_deleted=counts[ProjectionAction.FOREIGN_DELETED],
        duration_ms=round((perf_counter() - started) * 1000),
        unchanged=plan.unchanged,
    )


def _as_existing_event(payload: GoogleEventPayload, *, profile: ZoneProfile) -> ExistingEvent:
    read = read_span(payload.start, payload.end, profile=profile)
    return ExistingEvent(
        event_id=payload.id,
        interval=read.interval if isinstance(read, ReadSpan) else None,
        syncr_key=payload.private_property(SYNCR_KEY_PROPERTY),
        title=payload.summary or "",
        description=payload.description,
        location=payload.location,
    )
