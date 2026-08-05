"""The orders each of a week's collections is held in, one key per collection.

Determinism rather than legality. Each collection the checker reads is sorted, so a candidate
overlapping two members is rejected by naming the earlier one whatever order the inputs arrived in,
and a document holds its windows in an order its inputs cannot change. Without that, permuting an
input list would change a reason clause while changing no placement.

**Every key reads the whole of the value it orders, or ends in an identity that makes the rest
unreachable.** That is the property the module exists to hold, and it is the one a partial key
breaks silently: a stable sort on a key that cannot separate two unequal values returns the arrival
order, so the defect is invisible in any test that builds one week once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from syncr_domain.gaps import ForbiddenWindow
    from syncr_domain.identifiers import AnchorId, AreaId, RoutineId
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.off_plan import OffPlanPeriod
    from syncr_solver.inputs import Anchor, AreaBudget, FrameEntry


def span_key(interval: Interval) -> tuple[Instant, Instant]:
    """Span order. Instants rather than their text, so two zones' spellings compare as instants."""
    return (interval.start, interval.end)


def frame_key(entry: FrameEntry) -> tuple[Instant, Instant, str, str, RoutineId]:
    """Span order, ending in the occurrence's own identity so no two entries tie.

    The two fields it does not read, the minimum duration and the flex band, cannot separate two
    entries this key ties: such entries share a routine and an occurrence key, so they are one
    occurrence declared twice, they derive one block id, and a document refuses the pair.
    """
    return (*span_key(entry.interval), entry.title, entry.occurrence_key, entry.routine_id)


def anchor_key(anchor: Anchor) -> tuple[Instant, Instant, str, AnchorId]:
    """Span order, the title, then the commitment's identity. Every field an anchor carries."""
    return (*span_key(anchor.interval), anchor.title, anchor.anchor_id)


def period_key(period: OffPlanPeriod) -> tuple[Instant, Instant, bool, bool, str]:
    """Span order, then what survives inside the span and the user's word for it.

    The span alone is already total over a legal input, because two periods of one tenant never
    cover a common instant. The rest of the value is read anyway, so the order does not rest on an
    invariant this module does not check, and a period with no label is separated from one whose
    label is empty rather than tying with it.
    """
    return (
        *span_key(period.interval),
        period.keep_frame,
        period.label is None,
        period.label or "",
    )


def area_key(area: AreaBudget) -> AreaId:
    """The Area's own identity, which makes every other field it carries unreachable as a tie.

    One budget per Area per week, so two budgets sharing an identity are one Area declared twice
    and their figures would disagree about the same Area.
    """
    return area.area_id


# What the window order reads, which is every field a window carries. The anchor is NOT an identity
# here: one commitment casts up to four windows, so two of them can share a span, a label and an
# anchor while differing in kind, in scope, or in the Areas they forbid. A key stopping at the
# anchor would order such a pair by input arrival, and the document holds the windows in this order.
WINDOW_ORDER_FIELDS: Final = (
    "interval",
    "kind",
    "scope",
    "label",
    "forbidden_area_ids",
    "anchor_id",
)


def window_key(
    window: ForbiddenWindow,
) -> tuple[Instant, Instant, str, str, str, tuple[AreaId, ...], AnchorId]:
    return (
        *span_key(window.interval),
        window.kind.value,
        window.scope.value,
        window.label,
        window.forbidden_area_ids,
        window.anchor_id,
    )
