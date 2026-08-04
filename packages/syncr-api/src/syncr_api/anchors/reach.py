"""How far outside its own interval an anchor's shadows reach, and what a week must read.

:mod:`syncr_api.anchors.shadows` computes where each product goes. This module answers the
prior question a caller holding a span has to ask: which commitments can put a product inside
that span at all. It lives beside the geometry rather than in the week assembler, because the
answer is a property of the four products and one statement of it is what keeps the two from
drifting apart.

## The envelope, derived from the geometry rather than restated

    prep         = [start - prep_lead,     start - prep_lead + prep_duration)
    transit_out  = [start - transit_lead,  start - transit_lead + transit_duration)
    transit_back = [end,                   end + return_transit)
    recovery     = [end,                   end + post_buffer)

**Neither leading product ends after the commitment starts**, and that is a boundary rule
rather than an assumption: a type declaring prep is refused unless its prep lead covers the
prep duration plus the transit lead, and a transit lead is refused unless it covers the
journey. Both are check constraints on the table as well. So every product of an anchor
``[A, B)`` falls inside

    [A - max(prep_lead, transit_lead), B + max(return_transit, post_buffer))

with a lead counted only when the product it leads is actually declared: a zero duration
collapses its product, and a collapsed product reaches nowhere.

Both halves take a **maximum rather than a sum**. Prep and the outbound leg are each measured
from the commitment's start and run in parallel, and so are the return leg and recovery from
its end: recovery runs from ``end`` beside the journey home rather than after it.

## The span an assembly reads, and why the directions invert

A product of the anchor ``[A, B)`` overlaps the week ``[S, E)`` only if
``A - before < E`` and ``B + after > S``, which is ``A < E + before`` and ``B > S - after``.
So the span to read is the week widened **forwards by the largest lead** and **backwards by
the largest span measured from a commitment's end**.

The directions are the opposite way round from the direction each product reaches, and that is
the whole point of stating the derivation: a prep block reaching BACK into this week is cast by
a commitment AHEAD of it. An exam at Monday 09:30 with a 14-hour prep lead casts prep at
Sunday 19:30, which is the last evening of the PREVIOUS ISO week, so it is that week's
assembly that has to read forwards to find the exam. Widening that week backwards by the lead
instead would read a week of commitments that can cast nothing into it and still lose the prep.

## The read is therefore bounded by two column bounds

A lead is bounded at a week and a duration at a day, so the span read is at most the week plus
one day before it and one week after it. That bound is the reason the lead column has one:
without it a single declaration would widen every assembly's read without limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar

from syncr_api.anchors.records import ShadowDeclaration
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from collections.abc import Iterable

    from syncr_api.anchors.records import AnchorTypeSpecification


@dataclass(frozen=True, slots=True)
class ShadowReach:
    """How far one or more declarations cast outside a commitment's own interval, in minutes.

    ``before`` is measured from the commitment's START and ``after`` from its END, because that
    is what each product is measured from. Both are zero for a declaration that casts nothing,
    which is what an untyped commitment and a type of all zeroes both amount to.
    """

    before_minutes: int
    after_minutes: int

    NOTHING: ClassVar[ShadowReach]

    def widened(self, other: ShadowReach) -> ShadowReach:
        """The reach that covers both, which is the larger of each half."""
        return ShadowReach(
            before_minutes=max(self.before_minutes, other.before_minutes),
            after_minutes=max(self.after_minutes, other.after_minutes),
        )

    def envelope(self, anchor: Interval) -> Interval:
        """The span every product of a commitment at ``anchor`` falls inside."""
        return Interval(
            anchor.start - timedelta(minutes=self.before_minutes),
            anchor.end + timedelta(minutes=self.after_minutes),
        )


ShadowReach.NOTHING = ShadowReach(before_minutes=0, after_minutes=0)


def shadow_reach(specification: AnchorTypeSpecification) -> ShadowReach:
    """How far the products this declaration actually casts reach outside a commitment.

    A lead whose product collapsed contributes nothing: an ``Exam`` with a 14-hour prep lead
    and no prep duration casts no prep, so nothing of it reaches fourteen hours back.
    """
    declared = ShadowDeclaration.of(specification)
    leads = (
        specification.prep_lead_minutes if declared.prep else 0,
        specification.effective_transit_lead_minutes if declared.outbound_transit else 0,
    )
    trailing = (
        specification.return_transit_minutes if declared.return_transit else 0,
        specification.post_buffer_minutes if declared.recovery else 0,
    )
    return ShadowReach(before_minutes=max(leads), after_minutes=max(trailing))


def widest_reach(specifications: Iterable[AnchorTypeSpecification]) -> ShadowReach:
    """The reach that covers every declaration a tenant holds.

    One reach for the set rather than one per type, because which type each commitment carries
    is not known until the commitments have been read.
    """
    widest = ShadowReach.NOTHING
    for specification in specifications:
        widest = widest.widened(shadow_reach(specification))
    return widest


def casting_span(week: Interval, specifications: Iterable[AnchorTypeSpecification]) -> Interval:
    """The span holding every commitment that can cast a product inside ``week``.

    Widened forwards by the largest lead and backwards by the largest span measured from a
    commitment's end, for the reason the module docstring derives. Equal to ``week`` for a
    tenant whose types cast nothing, so an assembly reads exactly its own week.
    """
    reach = widest_reach(specifications)
    return Interval(
        week.start - timedelta(minutes=reach.after_minutes),
        week.end + timedelta(minutes=reach.before_minutes),
    )
