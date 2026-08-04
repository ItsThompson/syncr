"""The commitments and declarations the shadow suites are stated over, built once.

Two suites read this: the geometry one, which asserts what a single commitment casts, and the
collision one, which asserts which blocks survive when two commitments cast over each other. The
declarations themselves live in :mod:`tests.anchor_specifications`; what lives here is how a
declaration becomes a stored row, how a commitment becomes an anchor record, and how a set of
shadows is read back as something an assertion can compare whole.

Every instant is resolved in the zone the reference weeks are drawn in, so a figure in a test
reads as the figure on the rendered grid rather than as an offset from one.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, time, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_api.anchors import rules
from syncr_api.anchors.records import AnchorRecord, AnchorTypeRecord
from syncr_api.anchors.shadows import generate
from syncr_domain.intervals import Interval
from syncr_domain.zones import resolve_zone, to_instant
from tests.anchor_specifications import CAREER, DECLARED_AREAS, NOTHING, TRANSIT

if TYPE_CHECKING:
    from syncr_api.anchors.records import AnchorTypeSpecification
    from syncr_api.anchors.shadow_products import ShadowSet
    from syncr_domain.intervals import Instant
    from syncr_domain.zones import ZoneId

TENANT = uuid4()
SOURCE = uuid4()
LONDON = "Europe/London"
COMMITMENT = "Kontron Placement Interview"

# The Tuesday `block-states.html` renders the interview on.
INTERVIEW_DAY = date(2026, 2, 10)
# The Monday a 14-hour lead reaches back out of. Its Sunday belongs to the previous ISO week.
EXAM_MONDAY = date(2026, 2, 9)
# 01:00 becomes 02:00 in Europe/London on this date, so a lead across it loses an hour of wall
# time while keeping every minute of elapsed time.
SPRING_FORWARD = date(2026, 3, 29)


def at(on: date, hour: int, minute: int = 0, *, zone: ZoneId = LONDON) -> Instant:
    """The instant a wall time on this date names, in the zone the records are drawn in by default.

    ``zone`` is a parameter because a lead crossing a daylight-saving transition is read here, and
    the interesting transitions are not all in one zone: a 30-minute one and a midnight one both
    change the answer in ways an hour-long one cannot show.
    """
    return to_instant(time(hour, minute), on, zone)


def wall(instant: Instant, *, zone: ZoneId = LONDON) -> str:
    """``instant`` as a reader of that week's grid sees it: local date and local time."""
    return instant.astimezone(resolve_zone(zone)).strftime("%a %Y-%m-%d %H:%M")


def a_type(specification: AnchorTypeSpecification) -> AnchorTypeRecord:
    """``specification`` as a stored row, refused here if the boundary would refuse it.

    Every geometry a suite asserts is therefore stated over a declaration a tenant could really
    hold. A fixture the rules reject describes a shadow the product cannot cast, and a test
    reading one asserts arithmetic against itself.
    """
    rules.validate(specification, declared_areas=DECLARED_AREAS, declared_sources=())
    return AnchorTypeRecord(id=uuid4(), tenant_id=TENANT, rule_order=0, specification=specification)


def an_anchor(
    anchor_type: AnchorTypeRecord | None,
    *,
    start: Instant,
    minutes: int = 45,
    title: str = COMMITMENT,
) -> AnchorRecord:
    """One imported commitment carrying ``anchor_type``, or carrying none."""
    return AnchorRecord(
        id=uuid4(),
        tenant_id=TENANT,
        source_id=SOURCE,
        external_uid=f"{title}@example.ac.uk",
        series_uid=None,
        title=title,
        interval=Interval(start, start + timedelta(minutes=minutes)),
        location=None,
        anchor_type_id=None if anchor_type is None else anchor_type.id,
        type_overridden=False,
        possibly_stale=False,
    )


def an_interview_anchor(specification: AnchorTypeSpecification) -> tuple[AnchorRecord, ShadowSet]:
    """The 16:00-16:45 commitment the records render, and the shadows ``specification`` casts."""
    anchor_type = a_type(specification)
    anchor = an_anchor(anchor_type, start=at(INTERVIEW_DAY, 16))
    return anchor, generate(anchor, anchor_type)


def a_journey_only_type(*, lead: int, duration: int) -> AnchorTypeRecord:
    """A declaration that casts one outbound leg and nothing else."""
    return a_type(
        replace(
            NOTHING,
            transit_lead_minutes=lead,
            transit_duration_minutes=duration,
            transit_area_id=TRANSIT,
        )
    )


def a_prep_only_type(*, lead: int, duration: int) -> AnchorTypeRecord:
    """A declaration that casts one prep block and nothing else."""
    return a_type(
        replace(
            NOTHING, prep_lead_minutes=lead, prep_duration_minutes=duration, prep_area_id=CAREER
        )
    )


def spans(shadows: ShadowSet) -> tuple[tuple[str, str, str, str], ...]:
    """Every member of ``shadows``, as the four things a reader of the grid can tell apart.

    An inventory rather than a lookup: a claim about what a declaration does NOT cast is only
    worth making against the whole of what it does. A block and a window are told apart by the
    first element, because no origin is spelled the way any window kind is.
    """
    blocks = tuple(
        (
            block.origin.value,
            block.occurrence_key,
            wall(block.interval.start),
            wall(block.interval.end),
        )
        for block in shadows.blocks
    )
    windows = tuple(
        (
            window.kind.value,
            window.scope.value,
            wall(window.interval.start),
            wall(window.interval.end),
        )
        for window in shadows.forbidden
    )
    return blocks + windows


def keys(shadows: ShadowSet) -> tuple[tuple[str, str], ...]:
    """Which products these blocks are, by origin and occurrence key."""
    return tuple((block.origin.value, block.occurrence_key) for block in shadows.blocks)
