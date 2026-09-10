"""What a week's plan puts on the write target, and what it deliberately does not.

One rule decides whether two of the reference workflow's block classes reach the user's phone:

    **Blocks project, forbidden windows do not, and anchors are excluded because they came from a
    calendar in the first place.**

Every clause of that rule is load-bearing.

*Blocks project.* A task, habit, routine, concrete template entry, prep or transit block is a thing
the user acts on. ``Leave for Uni`` is the clearest case: it is useless if it is not on the phone.

*Forbidden windows do not.* A window is the ABSENCE of a block, so projecting a recovery span as an
event would tell the user to do nothing at 17:00. The same holds for an unattributed prep or transit
band and for an empty slot, whose stated reason is a syncr-side explanation rather than an
instruction. None of the three is a block, so none reaches this module's input: the exclusion is
structural rather than a filter, and a test drives a document holding all three to prove it.

*Anchors are excluded.* They already exist on the source calendar the user reads, so projecting them
would duplicate every lecture.

The origin table below is TOTAL over :class:`~syncr_domain.identity.Origin`, so a new kind of block
cannot silently reach the phone or silently fail to.

**The key is the block's own identity and nothing else.** The diff pairs on it, so it has to be
stable across a re-solve and independent of every value the reader sees: a block that moved keeps
its key, which is what makes a move a patch rather than a delete plus an insert. ``BlockId`` is
already exactly that, so it is used rather than re-derived, and an off-plan segment takes a key
built from the period and the local day for the same reason.

**A projected event carries no location.** No block holds one. ``Anchor.location`` is stored with no
reader, and an anchor does not project anyway; transit names a journey rather than a destination,
because P0 declares the journey on the anchor type instead of routing it. So the field is present in
the shape and always absent in the value, which a test states.

**The desired set is keyed on that key, and a collision is refused where the diff is computed.** One
binding produces one block per week, so two events sharing a key means a span was collected twice:
the live case is one crossing the ISO week boundary, which belongs to the week its start falls in
and is emitted from that week alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_api.calendars.projection import ProjectedEvent
from syncr_domain.habits import BindingSource
from syncr_domain.identity import Origin
from syncr_domain.reasons import Bound, DerivationSource, PlacedSource

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from syncr_api.offplan.segments import OffPlanSegment
    from syncr_domain.identifiers import OffPlanPeriodId
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import Block, PlanDocument
    from syncr_domain.reasons import BoundSource, ReasonRecord
    from syncr_domain.zones import Date

# Whether a block of each origin reaches the write target. Total over `Origin`, so a new member is
# a deliberate decision here rather than a default nobody chose: the two failure modes are a block
# class that silently never arrives, and time the user does not own appearing on their phone twice.
PROJECTS_BY_ORIGIN: Final[Mapping[Origin, bool]] = {
    Origin.FRAME: True,
    Origin.TEMPLATE_ENTRY: True,
    Origin.HABIT: True,
    Origin.TASK: True,
    Origin.ANCHOR: False,
    Origin.PREP: True,
    Origin.TRANSIT: True,
}

# What an off-plan segment's key is built from, so it cannot collide with a block's. A `BlockId` is
# 64 hexadecimal characters with no separator in it, so a prefixed form is distinguishable from one
# by inspection as well as by construction.
OFF_PLAN_KEY_PREFIX: Final = "off-plan"
_KEY_SEPARATOR: Final = ":"

OFF_PLAN_TITLE: Final = "Off plan"

OFF_PLAN_DESCRIPTION: Final = (
    "You declared this time off, so syncr plans nothing in it. Your calendar is deliberately "
    "empty here rather than empty because something went wrong."
)
# What `keep_frame` means to a reader: the routines still run, and nothing else does.
OFF_PLAN_WITH_FRAME_DESCRIPTION: Final = (
    "You declared this time off, so syncr plans nothing discretionary in it. Your routines still "
    "run; nothing else is scheduled."
)

# What a `bound` clause's source says in the words a reader sees on their phone. Total over
# `BoundSource`, which is a union of three vocabularies, so a source with no phrase would render a
# description naming a value from the code.
#
# `anchor` is unreachable today and is stated anyway: an anchor block does not project, so nothing
# builds an event from a clause bound to one. It is here because the mapping's totality is what
# makes a missing phrase impossible, and an entry that is merely unreachable costs a line.
_PHRASE_BY_BOUND_SOURCE: Final[Mapping[BoundSource, str]] = {
    DerivationSource.ROUTINE: "Fixed by your routine",
    DerivationSource.TEMPLATE_ENTRY: "Fixed by your day's shape",
    DerivationSource.ANCHOR: "An imported commitment",
    DerivationSource.ANCHOR_TYPE: "Reserved around a commitment",
    BindingSource.FIXED: "A habit on a fixed day",
    BindingSource.ROTATION: "Chosen by the rotation",
    BindingSource.QUEUE: "Taken from the queue",
    PlacedSource.SOLVER: "Placed by syncr",
}


def projects(origin: Origin) -> bool:
    """Whether a block of this origin reaches the write target."""
    return PROJECTS_BY_ORIGIN[origin]


def desired_events(
    documents: Iterable[PlanDocument],
    segments: Iterable[OffPlanSegment],
    *,
    horizon: Interval,
) -> list[ProjectedEvent]:
    """Everything syncr intends on the write target over ``horizon``.

    ``documents`` are the live plans of the weeks the horizon covers. A block belongs to the week
    its start falls in and is emitted from that week alone, so a frame span crossing the ISO
    boundary -- a Sunday-night ``Sleep`` running into Monday -- appears exactly once across a
    multi-week horizon. A collection that emitted it from both weeks would produce two events under
    one key, which the diff refuses rather than pairing one copy and never seeing the other.
    """
    return [
        *(one for document in documents for one in projected_blocks(document, horizon=horizon)),
        *projected_off_plan(segments),
    ]


def projected_blocks(document: PlanDocument, *, horizon: Interval) -> tuple[ProjectedEvent, ...]:
    """The events one week's plan intends on the write target, over ``horizon``.

    A block is included when it OVERLAPS the horizon, and it is never clipped to it: a projected
    event is the block, so trimming its end would put a time on the phone that the plan does not
    say. A block wholly outside the horizon is absent, which is the same bound the reconciliation
    reads the target over, so the two sets are drawn over one span.
    """
    return tuple(
        _as_event(block)
        for block in document.blocks
        if projects(block.origin) and block.interval.overlaps(horizon)
    )


def projected_off_plan(segments: Iterable[OffPlanSegment]) -> tuple[ProjectedEvent, ...]:
    """One event per off-plan day segment, so the user can see WHY a day is empty.

    Without these, a week declared off reads on the phone as a week syncr failed to plan, and the
    two look identical from a calendar client.
    """
    return tuple(
        ProjectedEvent(
            syncr_key=off_plan_key(segment.period_id, segment.on),
            interval=segment.interval,
            title=_off_plan_title(segment.label),
            description=(
                OFF_PLAN_WITH_FRAME_DESCRIPTION if segment.keep_frame else OFF_PLAN_DESCRIPTION
            ),
        )
        for segment in segments
    )


def off_plan_key(period_id: OffPlanPeriodId, on: Date) -> str:
    """The stable key one day segment of one off-plan period takes.

    Built from the period and the local day rather than from the segment's instants, so a segment
    whose length changes -- a period edited to start later, a transition day that is 23 hours --
    keeps the identity it had and is patched rather than replaced.
    """
    return _KEY_SEPARATOR.join((OFF_PLAN_KEY_PREFIX, str(period_id), on.isoformat()))


def rendered_reason(reason: ReasonRecord) -> str | None:
    """The event's description: the block's reason record, as one line a reader can act on.

    Today that is the ``bound`` clause, which names what determined the block. A future change is
    where a reason record first carries clauses beyond ``bound``, and therefore where a DOMINANT
    clause becomes available to prefer. Until then, a materialized block carries exactly one clause,
    leaving nothing to choose between. A record carrying no ``bound`` clause renders nothing rather
    than a sentence built from a clause kind this has no wording for.
    """
    bound = next((clause for clause in reason.clauses if isinstance(clause, Bound)), None)
    if bound is None:
        return None
    return f"{_PHRASE_BY_BOUND_SOURCE[bound.source]}: {bound.selected}"


def _as_event(block: Block) -> ProjectedEvent:
    return ProjectedEvent(
        syncr_key=block.id,
        interval=block.interval,
        title=block.title,
        description=rendered_reason(block.reason),
    )


def _off_plan_title(label: str | None) -> str:
    """What the segment is called: the user's own words when they gave any."""
    return f"{OFF_PLAN_TITLE}: {label}" if label else OFF_PLAN_TITLE
