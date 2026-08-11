"""What the drill's tenant declares, written through the services a person's requests reach.

Five declarations and no more: an Area to charge time to, a day type, a shape for that day type
holding one Area slot, that day type on all seven weekdays, and one rotation habit inside the Area.
That is the least a week can be solved from, and it is the least whose solve produces the two things
a restore drill has to compare: rows in the tables a plan writes, and a rotation cursor that has
moved off its first variant.

**Each step reads before it writes, so a second run declares nothing.** A drill is repeated, and a
seeder that appended a second Area every time would make the database it seeds a function of how
often the drill has run. The read is through the repositories and the write is through the services:
a service read answers an absent declaration with the rejection a route would return, which is not
what a convergence check is asking.

Settings are deliberately not declared. A tenant that has saved none reads the declared defaults,
which put the home zone at UTC, so the drill's week runs on the instants its own dates name and
nothing here has to state a zone to be reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from syncr_api.areas.declarations import AreaDeclaration
from syncr_api.areas.injection import get_area_service
from syncr_api.areas.repository import AreaRepository
from syncr_api.habits.declarations import DeclaredCadence, HabitDeclaration
from syncr_api.habits.injection import get_habit_service
from syncr_api.habits.repository import HabitRepository
from syncr_api.templates.declarations import DayTypeDeclaration, SlotEntry, TemplateDeclaration
from syncr_api.templates.injection import (
    get_day_type_service,
    get_template_service,
    get_week_pattern_service,
)
from syncr_api.templates.repository import (
    DayTypeRepository,
    TemplateRepository,
    WeekPatternRepository,
)
from syncr_domain.habits import BindingSource, CadenceKind, MissPolicy
from syncr_domain.templates import EntrySpan, TemplateEntryKind, WeekPattern
from syncr_domain.weeks import Weekday

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.principal import Principal
    from syncr_domain.identifiers import AreaId, DayTypeId, HabitId, TemplateId

AREA_NAME: Final = "Training"
DAY_TYPE_NAME: Final = "Every day"
TEMPLATE_NAME: Final = "Every day's shape"
HABIT_TITLE: Final = "Gym"

# The four variants the drill's cursor rotates through, and one confirmed completion is what puts it
# on the second of them. The same list the drill's hand-written seed used, so a fingerprint taken
# after either seeder reads the same variant names.
VARIANTS: Final = ("Chest", "Back", "Legs", "Shoulders")

# Noon, so the slot sits inside the default day window (07:00 to 23:00) and well after the instant
# the week is planned at, which is what keeps every day's slot fillable rather than elapsed.
SLOT_TIME: Final = time(12, 0)
SLOT_MINUTES: Final = 60

# Two occurrences, which is what makes the cursor's arithmetic a property of this seeder rather
# than of the solver's packing. Confirming a day settles every block in it, including one nobody
# recorded, so a week holding more occurrences than the two this seeder states an outcome for would
# put the cursor wherever the presumptions landed. With two, one completion is confirmed and one
# skip is, whichever days they were placed on.
OCCURRENCES_PER_WEEK: Final = 2

# The slot's duration falls inside this range, which is what makes the occurrence eligible for it.
HABIT_MIN_MINUTES: Final = 45
HABIT_MAX_MINUTES: Final = 90
DEBT_CAP_PERIODS: Final = 2


@dataclass(frozen=True, slots=True)
class DrillDeclarations:
    """What the drill's tenant has declared, as the identifiers the later steps name."""

    area_id: AreaId
    day_type_id: DayTypeId
    template_id: TemplateId
    habit_id: HabitId


async def declare(session: AsyncSession, principal: Principal) -> DrillDeclarations:
    """Declare whatever the drill's tenant is missing, and answer with the whole set."""
    area_id = await _an_area(session, principal)
    day_type_id = await _a_day_type(session, principal)
    template_id = await _a_shape(session, principal, day_type_id)
    await _a_slot(session, principal, template_id, area_id)
    await _every_weekday(session, principal, day_type_id)
    habit_id = await _a_rotation_habit(session, principal, area_id)
    return DrillDeclarations(
        area_id=area_id,
        day_type_id=day_type_id,
        template_id=template_id,
        habit_id=habit_id,
    )


async def _an_area(session: AsyncSession, principal: Principal) -> AreaId:
    """The Area every discretionary block of the drill's week is charged to."""
    for area in await AreaRepository(session, principal.tenant_id).list_all():
        if area.name == AREA_NAME:
            return area.id
    dealt = await get_area_service(principal, session).create(
        principal,
        AreaDeclaration(
            name=AREA_NAME,
            parent_id=None,
            budget_percent=Decimal(50),
            floor_hours=Decimal(2),
        ),
    )
    return dealt.area.id


async def _a_day_type(session: AsyncSession, principal: Principal) -> DayTypeId:
    for day_type in await DayTypeRepository(session, principal.tenant_id).list_all():
        if day_type.name == DAY_TYPE_NAME:
            return day_type.id
    created = await get_day_type_service(principal, session).create(
        principal, DayTypeDeclaration(name=DAY_TYPE_NAME)
    )
    return created.id


async def _a_shape(
    session: AsyncSession, principal: Principal, day_type_id: DayTypeId
) -> TemplateId:
    held = await TemplateRepository(session, principal.tenant_id).find_by_day_type(day_type_id)
    if held is not None:
        return held.id
    created = await get_template_service(principal, session).create(
        principal, TemplateDeclaration(day_type_id=day_type_id, name=TEMPLATE_NAME)
    )
    return created.id


async def _a_slot(
    session: AsyncSession, principal: Principal, template_id: TemplateId, area_id: AreaId
) -> None:
    """One Area slot on the shape: a declared hour whose content the solve decides."""
    shape = await TemplateRepository(session, principal.tenant_id).find(template_id)
    entries = shape.entries if shape is not None else ()
    if any(entry.kind is TemplateEntryKind.SLOT and entry.area_id == area_id for entry in entries):
        return
    await get_template_service(principal, session).add_entry(
        principal,
        template_id,
        SlotEntry(
            span=EntrySpan(
                target_time=SLOT_TIME, duration_minutes=SLOT_MINUTES, flex_band_minutes=0
            ),
            area_id=area_id,
        ),
    )


async def _every_weekday(
    session: AsyncSession, principal: Principal, day_type_id: DayTypeId
) -> None:
    """The one day type on all seven weekdays, which is what makes the pattern a pattern."""
    held = await WeekPatternRepository(session, principal.tenant_id).read()
    if held is not None:
        return
    await get_week_pattern_service(principal, session).replace(
        principal, WeekPattern(mapping=dict.fromkeys(Weekday, day_type_id))
    )


async def _a_rotation_habit(
    session: AsyncSession, principal: Principal, area_id: AreaId
) -> HabitId:
    """The habit whose cursor a restore has to re-derive to the same variant."""
    for habit in await HabitRepository(session, principal.tenant_id).list_all():
        if habit.title == HABIT_TITLE:
            return habit.id
    read = await get_habit_service(principal, session).create(
        principal,
        HabitDeclaration(
            area_id=area_id,
            title=HABIT_TITLE,
            cadence=DeclaredCadence(
                kind=CadenceKind.TIMES_PER_WEEK,
                times_per_week=OCCURRENCES_PER_WEEK,
                approx_days=None,
            ),
            min_duration_minutes=HABIT_MIN_MINUTES,
            max_duration_minutes=HABIT_MAX_MINUTES,
            miss_policy=MissPolicy.DEBT,
            binding_source=BindingSource.ROTATION,
            variants=VARIANTS,
            debt_cap_periods=DEBT_CAP_PERIODS,
        ),
    )
    return read.habit.id
