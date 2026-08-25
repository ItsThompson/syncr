"""The two things in a plan that explain a gap: a forbidden window and an empty slot.

A gap in the week is either something the solver may not fill or something it could not fill,
and the two are different types on purpose. Off-plan spans are a third thing that draws the
same way and they are not here either: they come from a user-declared entity with its own
lifecycle. **Three types, one drawing rule.** Keeping them distinct is what lets the
discretionary-time denominator treat each correctly.

**A forbidden window is deliberately not a block.** No fill, no Area rule, no state, because
what it exists to explain is that nothing is there. Whether it leaves the discretionary-time
denominator is not decided here: a window states which kind of span it is and
:mod:`syncr_domain.discretionary` holds the one table that says what each kind does to the
denominator.

**An empty slot is discretionary time that stayed unallocated.** It renders with the same
treatment and it is a separate type because subtracting it would make an unfillable week read
as a fully budgeted one. It is a first-class member of the document so the grid can draw a
stated gap rather than an unexplained one.

**Each empty-slot reason has exactly one gutter label, and it is defined here.** The grid, the
CLI, and the smoke scenarios all read this, so one state cannot acquire three wordings. In
particular ``not_solved`` does not borrow ``no_eligible_content``'s wording: nobody looked at
the backlog, so saying it was empty would state something no code computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from syncr_domain.discretionary import OccupancyKind
from syncr_domain.errors import DomainError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from syncr_domain.identifiers import AnchorId, AreaId
    from syncr_domain.intervals import Interval


class GapError(DomainError):
    """A band or a slot breaks one of the rules that make its emptiness explainable."""


class ForbiddenScope(StrEnum):
    """What a forbidden window forbids.

    Two members, where an anchor type's own control has three. A type may say it forbids
    nothing, and that generates no window at all, so by the time a window exists it forbids
    either every Area or a named set of them. A window that would forbid nothing is not one.
    """

    ALL = "all"
    AREAS = "areas"


class ForbiddenKind(StrEnum):
    """Why a span is forbidden. Three kinds, and only recovery can be scoped.

    An unattributed buffer is reserved time with no Area to claim it, which is exactly the
    condition that made it a window rather than a block.
    """

    RECOVERY = "recovery"
    PREP_UNATTRIBUTED = "prep_unattributed"
    TRANSIT_UNATTRIBUTED = "transit_unattributed"


class EmptySlotReason(StrEnum):
    """Why a template slot the solver could not fill is empty.

    ``not_solved`` is the materialized case, where no binding was attempted at all. It is a
    member of its own because nobody looked at the backlog, and every other member reports
    something a phase computed.

    ``elapsed`` is the one the clock decides rather than the backlog. The week had already
    reached the slot when the solve ran, so no content could be placed into it and none will
    be: whether the Area had any is a question the span never got to ask.

    ``dropped_leg`` is the one a collision decides rather than the solver. The anchor type
    declared the journey and another commitment's buffer took the time first, so the leg was
    dropped whole: the span stays empty and the emptiness has a stated cause instead of reading
    as time nothing ever claimed.
    """

    NO_ELIGIBLE_CONTENT = "no_eligible_content"
    OFF_PLAN = "off_plan"
    BLOCKED_BY_CONSTRAINT = "blocked_by_constraint"
    NOT_SOLVED = "not_solved"
    ELAPSED = "elapsed"
    DROPPED_LEG = "dropped_leg"


@dataclass(frozen=True, slots=True)
class SlotContext:
    """What a gutter label may name besides the reason itself.

    The Area is always available, because an empty slot has one. The period's label is the
    user's own word for a span they declared off, and it is optional because a span needs no
    name to suspend scheduling.
    """

    area_name: str
    off_plan_label: str | None = None


def _no_eligible_content(context: SlotContext) -> str:
    return f"no eligible {context.area_name} content"


def _off_plan(context: SlotContext) -> str:
    if context.off_plan_label is None:
        return "off plan"
    return f"off plan · {context.off_plan_label}"


def _no_legal_window(_: SlotContext) -> str:
    return "no legal window"


def _content_not_yet_chosen(_: SlotContext) -> str:
    return "content not yet chosen"


def _already_begun(_: SlotContext) -> str:
    return "already begun"


def _journey_dropped(_: SlotContext) -> str:
    return "journey dropped"


# One label per reason. The conditional half of the off-plan wording lives inside that
# member's own renderer rather than in a branch every reason passes through, so adding a
# reason cannot change what another one renders.
_LABEL_BY_REASON: Final[Mapping[EmptySlotReason, Callable[[SlotContext], str]]] = {
    EmptySlotReason.NO_ELIGIBLE_CONTENT: _no_eligible_content,
    EmptySlotReason.OFF_PLAN: _off_plan,
    EmptySlotReason.BLOCKED_BY_CONSTRAINT: _no_legal_window,
    EmptySlotReason.NOT_SOLVED: _content_not_yet_chosen,
    EmptySlotReason.ELAPSED: _already_begun,
    EmptySlotReason.DROPPED_LEG: _journey_dropped,
}


def gutter_label(reason: EmptySlotReason, context: SlotContext) -> str:
    """The one string an empty slot of this reason renders beside itself."""
    return _LABEL_BY_REASON[reason](context)


@dataclass(frozen=True, slots=True)
class ForbiddenWindow:
    """A span the solver may not fill, drawn so that its emptiness is explained.

    It names the anchor that cast it, so the gutter can say which commitment reserved the
    time. The label is stored rather than derived at render time, because a document is a fact
    about a week: an anchor retitled in March must not change what a week approved in February
    says.
    """

    interval: Interval
    kind: ForbiddenKind
    scope: ForbiddenScope
    forbidden_area_ids: tuple[AreaId, ...]
    label: str
    anchor_id: AnchorId

    def __post_init__(self) -> None:
        object.__setattr__(self, "forbidden_area_ids", tuple(self.forbidden_area_ids))
        _require_a_scope_matching_the_areas(self.scope, self.forbidden_area_ids)
        _require_an_unattributed_buffer_to_forbid_everything(self.kind, self.scope)
        if not self.label:
            raise GapError(
                "a forbidden window's label is what explains the gap in the gutter, and an "
                "empty one explains nothing. Whether a whitespace-only label explains "
                "anything is a question about text, answered where text is fitted to a column"
            )

    @property
    def occupancy_kind(self) -> OccupancyKind:
        """Which kind of span the discretionary-time denominator reads this window as.

        Stated as a mapping into that vocabulary rather than as a second answer to "is this
        subtracted": the subtraction table has one home, and a caller assembling the four
        subtrahends asks it rather than reading a scope twice.
        """
        if self.kind is not ForbiddenKind.RECOVERY:
            return OccupancyKind.UNATTRIBUTED_BUFFER
        if self.scope is ForbiddenScope.ALL:
            return OccupancyKind.RECOVERY_ALL
        return OccupancyKind.RECOVERY_AREAS

    def forbids(self, area_id: AreaId) -> bool:
        """Whether this window forbids work for this Area.

        The one reading of the scope, so a caller never has to decide what an empty list of
        Areas means: a window that forbids everything forbids every Area, including ones
        declared after it was generated.
        """
        return self.scope is ForbiddenScope.ALL or area_id in self.forbidden_area_ids


@dataclass(frozen=True, slots=True)
class EmptySlot:
    """A template slot the solver could not fill, and the stated reason it could not."""

    interval: Interval
    area_id: AreaId
    reason: EmptySlotReason

    def gutter_label(self, context: SlotContext) -> str:
        """What this slot renders beside itself. One wording per reason, defined once."""
        return gutter_label(self.reason, context)


def _require_a_scope_matching_the_areas(
    scope: ForbiddenScope, forbidden_area_ids: tuple[AreaId, ...]
) -> None:
    """FW1, as one equality between two conditions rather than two rules that could disagree.

    A window naming Areas forbids exactly those; a window naming none forbids everything. An
    earlier draft used an empty list to mean "forbids everything", which reads as an oversight
    rather than a decision and cannot express "forbids nothing" at all.
    """
    if (scope is ForbiddenScope.AREAS) != bool(forbidden_area_ids):
        named = "the Areas it forbids" if scope is ForbiddenScope.AREAS else "no Areas"
        raise GapError(
            f"a {scope.value!r} window names {named}, and this one names "
            f"{len(forbidden_area_ids)}: the scope says what a window forbids so that an empty "
            "list never has to"
        )


def _require_an_unattributed_buffer_to_forbid_everything(
    kind: ForbiddenKind, scope: ForbiddenScope
) -> None:
    """FW3: reserved time with no Area cannot be claimed by one.

    A prep or transit buffer becomes a window only when its anchor type named no Area for it,
    so there is no Area to scope it to. Recovery is the one kind whose scope a user chooses.
    """
    if kind is ForbiddenKind.RECOVERY or scope is ForbiddenScope.ALL:
        return
    raise GapError(
        f"a {kind.value!r} window forbids every Area: it exists because its buffer had no Area "
        f"to belong to, so there is none to scope it to. Only {ForbiddenKind.RECOVERY.value!r} "
        "carries a scope the user chose"
    )
