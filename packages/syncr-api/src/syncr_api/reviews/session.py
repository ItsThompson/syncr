"""The weekly session's reading: last week's retrospective, next week's raises, and the verdict.

``US-REV-01``: planning and retrospective happen in one pass, so last week informs next week without
a second sitting. That is why one payload carries both halves, and why the week it is addressed by
is the week being PLANNED: the retrospective covers the week before it.

**Nothing here writes.** No revision, no operation, no version bump, and no ``VerdictEvent``. The
verdict on this payload is computed the same way the Week screen's is, through the same
collaborator, and no read path records the transition it observes. That rule is enforced by a guard
stated over the response shapes that carry a verdict rather than over a list of paths, so this
payload came under it the moment it declared the field.

**Every figure is someone else's arithmetic.** The retrospective's actual-against-target is the pie
review's ``categories_of``; the verdict and the concessions are the week view's; an at-risk task is
``plans.at_risk``'s determination. A second arithmetic anywhere here would be the one that quietly
disagreed with the screen the user was looking at ten seconds earlier.

**The two composers live beside the shape they build**, which is why this module holds both the
value and the assembly of it. The service reads the rows and hands them over; deciding which reading
each field takes is one subject, and splitting it from the fields would put a payload's shape in one
file and its meaning in another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.offplan.reading import off_plan_reading
from syncr_api.plans.at_risk import tasks_at_risk
from syncr_api.promotions.absorption import accept_refusal
from syncr_api.reviews.collisions import repeated_collision_items, repeated_collisions
from syncr_api.reviews.config import CHRONIC_SKIP_WEEKS, REPEATED_COLLISION_WEEKS
from syncr_api.reviews.naming import (
    a_kind,
    block_titles,
    content_title,
)
from syncr_api.reviews.raised import (
    at_risk_items,
    cadence_items,
    floor_items,
    habit_debt_items,
    new_anchor_items,
    overdue_items,
)
from syncr_api.reviews.readings import categories_of
from syncr_api.reviews.skips import chronic_skip_items, chronic_skips

if TYPE_CHECKING:
    from collections.abc import Container, Iterable, Iterator, Mapping, Sequence
    from datetime import datetime
    from uuid import UUID

    from syncr_api.offplan.reading import OffPlanReading
    from syncr_api.plans.records import WeekAdjustmentRecord
    from syncr_api.plans.week_views import WeekView
    from syncr_api.reviews.coverage import DayCounts
    from syncr_api.reviews.history import ReviewedWeek
    from syncr_api.reviews.raised import RaisedItem
    from syncr_api.reviews.readings import CategoryReading
    from syncr_api.reviews.session_sources import SessionFacts
    from syncr_domain.budgets import AreaShare
    from syncr_domain.feasibility import Verdict
    from syncr_domain.identity import BindingKind
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import Block, PlanDocument
    from syncr_domain.promotion import PromotionCandidate
    from syncr_domain.weeks import IsoWeek

    # What `BindingRef.content_key` answers, which is what a block title is looked up by.
    type ContentKey = tuple[BindingKind, UUID, int | None]


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionRetro:
    """Last week, as the session reports it.

    ``discretionary_minutes`` is the reviewed week's own stored figure, or ``None`` when that week
    held no plan of record: a target divides a denominator such a week does not have.

    ``days`` is what ``US-REV-04`` asks for, and the three counts are three quantities. Off-plan
    days are reported separately from unconfirmed ones, because a day the user declared away is not
    a day they failed to answer for."""

    iso_week: IsoWeek
    span: Interval
    discretionary_minutes: int | None
    days: DayCounts
    off_plan: OffPlanReading
    categories: tuple[CategoryReading, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class NamedPromotion:
    """One promotion candidate with the name the reader knows its content by, and what can be done.

    The candidate itself carries no name: the rule that finds it reads pin rows, which store a
    binding and no title. Resolving the name HERE rather than on a client is what stops two surfaces
    of one payload spelling the same absence two ways, which is what happened while the client held
    its own fallback.

    ``accept_refusal`` is why the template cannot absorb this pattern, or ``None`` when it can. It
    is on the raise rather than left to the accept to discover, so no surface draws a control that
    will be refused: the product states a limit where the reader meets it rather than letting them
    find it by pressing.
    """

    candidate: PromotionCandidate
    title: str
    accept_refusal: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class WeeklySessionReading:
    """One weekly session: the week it plans, the week it reviews, and everything raised between.

    ``verdict`` and ``concessions`` are the week being planned, not the week under review. The
    session is a planning surface first: the retrospective is what informs it, and the verdict is
    what the one approve action is taken against.

    ``verdict`` is ``None`` exactly when the planned week holds no plan, which is the same
    biconditional the week's own read states: nothing has been computed about such a week, so a
    verdict beside it would be a claim about nothing.
    """

    iso_week: IsoWeek
    span: Interval
    retro: SessionRetro
    raised: tuple[RaisedItem, ...]
    verdict: Verdict | None
    concessions: Sequence[WeekAdjustmentRecord]
    promotions: tuple[NamedPromotion, ...]
    input_version: int


def promotions_of(
    candidates: Iterable[PromotionCandidate],
    *,
    titles: Mapping[ContentKey, str],
    declined: Container[str],
) -> tuple[NamedPromotion, ...]:
    """Each candidate the reader has not already answered, named, with what can be done about it.

    The lookup drops the split index, because a repeated pin groups across chunks deliberately: a
    candidate for a divided task names the task. That is why it is :func:`content_title` rather
    than a direct read of the map, which is what a caller holding a whole content key uses.

    **A declined pattern is dropped here rather than in the detection.** The rule answers what the
    pins say, which is a fact about the plan; whether to ASK about it is a fact about the reader,
    and the two are separate so a suppression cannot quietly change what the nightly run reports
    finding.
    """
    raised = []
    for candidate in candidates:
        if candidate.ref.id in declined:
            continue
        title = content_title(
            titles, kind=candidate.ref.kind, entity_id=candidate.ref.entity_id
        ) or a_kind(candidate.ref.kind)
        raised.append(
            NamedPromotion(
                candidate=candidate,
                title=title,
                accept_refusal=accept_refusal(candidate.ref, title=title),
            )
        )
    return tuple(raised)


def retro_of(week: ReviewedWeek, *, shares: Sequence[AreaShare]) -> SessionRetro:
    """Last week's actual against target per Area, over the pie review's own arithmetic."""
    return SessionRetro(
        iso_week=week.iso_week,
        span=week.span,
        discretionary_minutes=week.discretionary_minutes,
        days=week.counts,
        off_plan=off_plan_reading(week.span, week.off_plan),
        categories=categories_of(week, shares=shares),
    )


def titles_of(
    reviewed: Sequence[ReviewedWeek], planned: PlanDocument | None
) -> Mapping[ContentKey, str]:
    """What the session can call each content it names, from the blocks it can see.

    Read once and handed to both readers that need a name: the repeated collision's block and the
    promotion candidate's binding. A conflict row and a pin row each store a binding and no title,
    so the window's own blocks are the only place a name exists without a second read.
    """
    return block_titles(_blocks_of(reviewed, planned))


def raised_of(
    view: WeekView,
    reviewed: Sequence[ReviewedWeek],
    facts: SessionFacts,
    *,
    titles: Mapping[ContentKey, str],
    now: datetime,
) -> tuple[RaisedItem, ...]:
    """Every raised item, in the order section 16's `raised` list gives them.

    The order is the payload's, not a client's: a panel renders rows in the order it receives them,
    and two clients choosing their own would give one week two shapes.
    """
    at_risk = tasks_at_risk(view.verdict, facts.open_tasks)
    return (
        *chronic_skip_items(chronic_skips(reviewed, consecutive_weeks=CHRONIC_SKIP_WEEKS)),
        *habit_debt_items(facts.habits, facts.debt),
        *floor_items(view.verdict),
        *overdue_items(facts.open_tasks, now=now),
        *at_risk_items(one for one in facts.open_tasks if one.id in at_risk),
        *new_anchor_items(facts.arriving),
        *cadence_items(view.live, facts.habits),
        *repeated_collision_items(
            repeated_collisions(facts.conflicts, at_least_weeks=REPEATED_COLLISION_WEEKS),
            titles=titles,
        ),
    )


def _blocks_of(reviewed: Sequence[ReviewedWeek], planned: PlanDocument | None) -> Iterator[Block]:
    """Every block the session can see, oldest week first and the planned week last.

    The order is what makes a rename resolve to the latest name: :func:`block_titles` keeps the last
    title it is handed for one content.
    """
    for week in reviewed:
        for day in week.days:
            yield from day.blocks
    if planned is not None:
        yield from planned.blocks
