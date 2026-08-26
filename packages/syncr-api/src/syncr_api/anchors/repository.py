"""Persistence for ``anchors``. Tenant-scoped, and the only writer of an imported fact.

Every statement is built from the scoped base, so the tenant predicate is applied by the base
rather than remembered per method, and a repository cannot be constructed without a tenant.

There is no method that changes an anchor's title, interval, or location on its own. The only
writer of those is :meth:`AnchorRepository.update_fact`, which the reconciler calls with what
the source just published, so "read-only in syncr" is a property of this surface rather than of
the route table alone.

Three methods are worth reading twice.

:meth:`in_span` is keyset-paginated rather than offset-paginated. A feed may legitimately
contribute thousands of anchors inside a year, and an offset page shifts under a sync that
inserts a row before the cursor, which would silently skip an anchor. The key is
``(starts_at, id)``, which the span index leads with.

:meth:`overlapping` answers the same question with no page at all, and the difference is the
caller. A page limit reports what fits and says nothing about the rest, so a week assembly
reading one page would silently lose the occupancy of whatever fell past it, which is the one
failure that read exists to prevent. What bounds it instead is the span, and the bound is checked
rather than argued: the widest span an assembly can ask for is derived from the two minute bounds
an anchor type's columns carry, so a caller asking for more than that is not assembling a week.

:meth:`retype_series` is what makes a retype persist on the series. It writes by ``series_uid``
rather than by identifier, so one call types every occurrence of a daily standup, including the
ones the user is not looking at.

:meth:`release_type` clears the override flag as well as the identifier. An override naming a
type nobody can name any more is a state no route could leave.

No method commits. One request is one transaction, opened and committed by
:func:`syncr_api.core.db.get_transaction`; the worker opens its own around a tick.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func, or_

from syncr_api.anchors.config import ASSEMBLY_READ_MINUTES_MAX
from syncr_api.anchors.models import Anchor
from syncr_api.anchors.records import AnchorRecord
from syncr_api.core.repository import TenantScopedRepository
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import datetime

    from syncr_api.anchors.records import AnchorTypeId
    from syncr_api.calendars.records import CalendarSourceId
    from syncr_domain.identifiers import AnchorId


class SpanTooWideForOneRead(ValueError):
    """A caller asked the unpaged read for a span no assembly of a week could need.

    Not part of the error vocabulary a service raises, for the same reason a plan write's two
    rejections are not: the only caller derives its span from a week and two capped columns, so a
    span past the bound is a defect in the caller rather than something a request can correct. It
    renders as the generic 500 the catch-all handler produces, and the fault is logged there.
    """


class AnchorRepository(TenantScopedRepository):
    """Reads, reconciles, and retypes one tenant's anchors."""

    async def in_span(
        self, span: Interval, *, limit: int, after: tuple[datetime, AnchorId] | None = None
    ) -> tuple[AnchorRecord, ...]:
        """This tenant's anchors overlapping ``span``, earliest first, one page at a time.

        Overlapping rather than contained: a lecture that began before the span and runs into it
        occupies time inside it, and a read that missed it would report a free hour the user is
        sitting in a lecture theatre for.
        """
        statement = (
            self.scoped_select(Anchor)
            .where(Anchor.starts_at < span.end, Anchor.ends_at > span.start)
            .order_by(Anchor.starts_at, Anchor.id)
            .limit(limit)
        )
        if after is not None:
            starts_at, anchor_id = after
            # The keyset step, written out rather than as a row-value comparison: the two forms
            # plan identically against `(tenant_id, starts_at)` and this one needs no cast to
            # type-check.
            statement = statement.where(
                or_(
                    Anchor.starts_at > starts_at,
                    (Anchor.starts_at == starts_at) & (Anchor.id > anchor_id),
                )
            )
        found = await self._session.scalars(statement)
        return tuple(as_anchor_record(row) for row in found)

    async def overlapping(self, span: Interval) -> tuple[AnchorRecord, ...]:
        """Every anchor of this tenant's overlapping ``span``, earliest first. No page.

        Overlapping on the same reading as :meth:`in_span`: a commitment that began before the
        span occupies time inside it. Unpaged because the caller is an assembly rather than an
        interface, and an assembly that read one page would report time as free that a page
        boundary happened to hide.

        Bounded by the widest span one assembly can ask for, which is a week plus the reach two
        capped columns permit. The bound is here rather than in the caller because it is what makes
        the read safe to reach for: without it the next caller that finds paging inconvenient gets
        an unbounded scan of a table a feed can fill.
        """
        _require_a_span_one_assembly_could_need(span)
        found = await self._session.scalars(
            self.scoped_select(Anchor)
            .where(Anchor.starts_at < span.end, Anchor.ends_at > span.start)
            .order_by(Anchor.starts_at, Anchor.id)
        )
        return tuple(as_anchor_record(row) for row in found)

    async def find(self, anchor_id: AnchorId) -> AnchorRecord | None:
        """One anchor of this tenant's, or ``None``.

        Scoped, so another tenant's identifier reads as absent rather than as forbidden, which
        is what makes the 404 the service raises truthful.
        """
        found = await self._session.scalar(self.scoped_select(Anchor).where(Anchor.id == anchor_id))
        return as_anchor_record(found) if found is not None else None

    async def list_for_source(self, source_id: CalendarSourceId) -> tuple[AnchorRecord, ...]:
        """Every anchor this source contributes, earliest first.

        The reconciler's whole prior state: the reconciliation keys it holds, and the series
        overrides it must carry forward.
        """
        found = await self._session.scalars(
            self.scoped_select(Anchor)
            .where(Anchor.source_id == source_id)
            .order_by(Anchor.starts_at, Anchor.id)
        )
        return tuple(as_anchor_record(row) for row in found)

    async def count_for_source(self, source_id: CalendarSourceId) -> int:
        """How many anchors this source currently contributes."""
        counted = await self._session.scalar(
            self.scoped_select(Anchor)
            .where(Anchor.source_id == source_id)
            .with_only_columns(func.count())
            .order_by(None)
        )
        return counted or 0

    async def start_instants_for_source(
        self, source_id: CalendarSourceId, *, span: Interval
    ) -> tuple[datetime, ...]:
        """Every instant an anchor of this source begins at in ``span``, earliest first.

        Beginning inside rather than overlapping, which is the opposite reading from the two reads
        above and deliberately: the caller asks which local DAYS this source fed, and a commitment
        belongs to the day it starts in wherever this product answers that question.

        Instants rather than rows, because the one caller wants dates. It reads no title, no
        location and no type, so a notice about a failing feed cannot come to disclose what is on
        the days it names.

        Repeats are kept. Two commitments starting at one instant are two rows here and one date to
        the caller, which already collapses instants to dates and would collapse these with them.
        """
        found = await self._session.scalars(
            self.scoped_select(Anchor)
            .where(
                Anchor.source_id == source_id,
                Anchor.starts_at >= span.start,
                Anchor.starts_at < span.end,
            )
            .with_only_columns(Anchor.starts_at)
            .order_by(Anchor.starts_at)
        )
        return tuple(found)

    async def list_matchable(self) -> tuple[AnchorRecord, ...]:
        """Every anchor whose type a rule may still decide, earliest first.

        An overridden anchor is absent: the user typed it, and re-evaluating rules must not undo
        that. Reading the set rather than issuing one ``UPDATE`` per type is what lets
        first-match semantics live in one function the reconciler uses too.
        """
        found = await self._session.scalars(
            self.scoped_select(Anchor)
            .where(Anchor.type_overridden.is_(False))
            .order_by(Anchor.starts_at, Anchor.id)
        )
        return tuple(as_anchor_record(row) for row in found)

    async def create(
        self,
        *,
        source_id: CalendarSourceId,
        external_uid: str,
        series_uid: str | None,
        title: str,
        interval: Interval,
        location: str | None,
        anchor_type_id: AnchorTypeId | None,
        type_overridden: bool,
    ) -> AnchorRecord:
        """Persist one anchor. The caller has already bounded every publisher-chosen value."""
        row = Anchor(
            id=uuid4(),
            tenant_id=self.tenant_id,
            source_id=source_id,
            external_uid=external_uid,
            series_uid=series_uid,
            title=title,
            starts_at=interval.start,
            ends_at=interval.end,
            location=location,
            anchor_type_id=anchor_type_id,
            type_overridden=type_overridden,
            possibly_stale=False,
        )
        self._session.add(row)
        # Flushed here so a duplicate reconciliation key surfaces as this call's failure rather
        # than at commit, after the pass has already reported what it did.
        await self._session.flush()
        return as_anchor_record(row)

    async def update_fact(
        self,
        anchor_id: AnchorId,
        *,
        series_uid: str | None,
        title: str,
        interval: Interval,
        location: str | None,
        anchor_type_id: AnchorTypeId | None,
        type_overridden: bool,
    ) -> None:
        """Replace what the source says about one anchor, and the type that follows from it.

        The whole fact in one statement, because one published event is one revision of it: a
        field-by-field update would let a moved interval land while a retitled summary did not,
        and the matched type is derived from the title, so the two cannot be written apart.
        """
        await self._session.execute(
            self.scoped_update(Anchor)
            .where(Anchor.id == anchor_id)
            .values(
                series_uid=series_uid,
                title=title,
                starts_at=interval.start,
                ends_at=interval.end,
                location=location,
                anchor_type_id=anchor_type_id,
                type_overridden=type_overridden,
                possibly_stale=False,
            )
        )

    async def remove_absent(self, source_id: CalendarSourceId, *, keeping: Collection[str]) -> int:
        """Delete this source's anchors whose key the feed no longer publishes, and count them.

        Called only after an attempt that actually read the feed. ``keeping`` empty is legal and
        means the feed published nothing, which is a different fact from a feed that could not be
        read: the caller distinguishes the two and calls this only for the former.
        """
        statement = self.scoped_delete(Anchor).where(Anchor.source_id == source_id)
        if keeping:
            statement = statement.where(Anchor.external_uid.not_in(keeping))
        return await self._affected_rows(statement)

    async def remove_reported(self, source_id: CalendarSourceId, *, keys: Collection[str]) -> int:
        """Delete this source's anchors whose removal a delta named by identifier, and count them.

        The delta-side counterpart of :meth:`remove_absent`, and its opposite in what absence
        means: a list of changes is silent about everything it did not mention, so only the keys
        the provider explicitly reported removed are taken off here. A set with no members removes
        nothing, which is what a delta that reported no removals means rather than a calendar that
        lists nothing.
        """
        return await self._affected_rows(
            self.scoped_delete(Anchor).where(
                Anchor.source_id == source_id, Anchor.external_uid.in_(keys)
            )
        )

    async def set_possibly_stale(self, source_id: CalendarSourceId, *, stale: bool) -> int:
        """Mark or clear this source's anchors as possibly stale, and report how many moved."""
        return await self._affected_rows(
            self.scoped_update(Anchor)
            .where(Anchor.source_id == source_id, Anchor.possibly_stale.is_(not stale))
            .values(possibly_stale=stale)
        )

    async def retype_series(
        self, *, source_id: CalendarSourceId, series_uid: str, anchor_type_id: AnchorTypeId | None
    ) -> int:
        """Retype every occurrence of one series, and report how many were retyped.

        Scoped to the source as well as the series, because a series UID is only unique within
        the calendar that published it.
        """
        return await self._affected_rows(
            self.scoped_update(Anchor)
            .where(Anchor.source_id == source_id, Anchor.series_uid == series_uid)
            .values(anchor_type_id=anchor_type_id, type_overridden=True)
        )

    async def retype_one(self, anchor_id: AnchorId, *, anchor_type_id: AnchorTypeId | None) -> int:
        """Retype one occurrence, and report whether it moved. For an anchor with no series."""
        return await self._affected_rows(
            self.scoped_update(Anchor)
            .where(Anchor.id == anchor_id)
            .values(anchor_type_id=anchor_type_id, type_overridden=True)
        )

    async def set_matched_type(
        self, anchor_id: AnchorId, *, anchor_type_id: AnchorTypeId | None
    ) -> None:
        """Assign the type a rule matched. Leaves ``type_overridden`` alone, which is False."""
        await self._session.execute(
            self.scoped_update(Anchor)
            .where(Anchor.id == anchor_id)
            .values(anchor_type_id=anchor_type_id)
        )

    async def release_type(self, anchor_type_id: AnchorTypeId) -> int:
        """Clear one type off every anchor holding it, override included, and count them.

        Called before the type is deleted. The override is cleared as well as the identifier,
        because an override naming a type nobody can name any more is a state no route can leave:
        the anchor would stay untyped forever while a rule that does match sits beside it. The
        foreign key's ``SET NULL`` is the backstop for the identifier; this decides the flag.
        """
        return await self._affected_rows(
            self.scoped_update(Anchor)
            .where(Anchor.anchor_type_id == anchor_type_id)
            .values(anchor_type_id=None, type_overridden=False)
        )


def _require_a_span_one_assembly_could_need(span: Interval) -> None:
    """Refuse a span wider than the widest week an assembly can widen its read to.

    The figure is derived from the lead and duration bounds an anchor type's columns carry, so it
    moves with them rather than being a number chosen here.
    """
    asked = span.total_minutes()
    if asked <= ASSEMBLY_READ_MINUTES_MAX:
        return
    raise SpanTooWideForOneRead(
        f"an unpaged anchor read covers at most {ASSEMBLY_READ_MINUTES_MAX} minutes and this one "
        f"asked for {asked}: that is wider than a week widened by the largest lead and the largest "
        "buffer any anchor type may declare, taken once for what lands in the week and once more "
        "for what collides with it, so it is not one week's assembly. Read it in weeks, or page it"
    )


def as_anchor_record(row: Anchor) -> AnchorRecord:
    """One mapped row as the frozen view every caller above hands back."""
    return AnchorRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        source_id=row.source_id,
        external_uid=row.external_uid,
        series_uid=row.series_uid,
        title=row.title,
        interval=Interval(row.starts_at, row.ends_at),
        location=row.location,
        anchor_type_id=row.anchor_type_id,
        type_overridden=row.type_overridden,
        possibly_stale=row.possibly_stale,
    )
