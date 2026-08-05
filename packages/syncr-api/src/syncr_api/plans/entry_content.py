"""What a concrete template entry becomes: the name its block carries, and the Area it charges.

A block carries the resolved content name and, unless it is the frame or an anchor, an Area. An
entry declares neither: it names a routine or a habit, and both live in tables with no shared
parent. This module resolves that pair against those rows, so the snapshot carries an entry only
when a block can be built from it.

**The resolution happens here rather than in the snapshot** because no join inside the snapshot is
total: a habit's occurrences are cadence-filtered and a routine's occurrences can be suppressed by
an off-plan period, so an entry naming either could find no name at all.

## Two states are dropped and three are refused, and the difference is what the table allows

:class:`DropCause` names the two states a stored row can really hold, both of them producer defects
the template boundary does not yet refuse: a binding naming no row this tenant has, and a concrete
entry naming a routine while declaring no Area, which no block can carry because a routine has none.
Dropping is the degradation an anchor carrying an unread type already takes: the rest of the week
assembles, and refusing would fail every solve, pin and live verdict for the week over one row.

Three states are refused instead, because the tables forbid them: a slot with no Area, a concrete
entry with no binding, and content with an empty title. The check constraint
``kind_states_its_binding`` enforces the first two for every writer there will ever be, and the
routine and habit boundaries both require a non-empty title. A cause an operator can never see is
worse than no cause, so these raise where they can name the row rather than joining a vocabulary of
states that cannot occur.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from syncr_common.logging import get_logger
from syncr_domain.templates import BindingTarget, TemplateEntryKind

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from syncr_api.habits.records import HabitRecord
    from syncr_api.routines.records import RoutineRecord
    from syncr_api.templates.records import TemplateEntryRecord
    from syncr_domain.identifiers import AreaId
    from syncr_solver.inputs import EntryBinding

_log = get_logger("syncr.plans")


class EntryPairingRejected(ValueError):
    """A stored entry contradicts a pairing its own table, or a boundary, already enforces."""


class DropCause(StrEnum):
    """Why an entry a week holds cannot become a block. One member per reachable cause.

    Closed, and counted per cause in the log line, so an operator reading a dropped entry can tell a
    dangling binding from an entry nothing can charge.
    """

    CONTENT_THIS_TENANT_DOES_NOT_HAVE = "content_this_tenant_does_not_have"
    CONTENT_WITH_NO_AREA_AND_NONE_DECLARED = "content_with_no_area_and_none_declared"


@dataclass(frozen=True, slots=True)
class EntryContent:
    """What a concrete entry's binding names: the title a block carries, and its Area.

    A routine has no Area, because the frame is not a category competing with Fitness. An entry
    naming one therefore has to declare an Area of its own, and the block it becomes carries that.
    """

    title: str
    area_id: AreaId | None = None


@dataclass(frozen=True, slots=True)
class Charged:
    """What the block an entry becomes is called, and which Area its minutes are charged to."""

    area_id: AreaId
    title: str | None = None


def content_by_binding(
    routines: Sequence[RoutineRecord], habits: Sequence[HabitRecord]
) -> Mapping[tuple[BindingTarget, UUID], EntryContent]:
    """Every row a concrete entry may name, keyed by the pair that names it.

    Keyed by the target as well as the identifier, so an entry whose target says ``habit`` cannot
    resolve against a routine that happens to share an identifier. That is the whole reason the
    target column exists: the two live in separate tables with no shared parent.
    """
    routine_content = {
        (BindingTarget.ROUTINE, routine.id): EntryContent(title=routine.title)
        for routine in routines
    }
    habit_content = {
        (BindingTarget.HABIT, habit.id): EntryContent(title=habit.title, area_id=habit.area_id)
        for habit in habits
    }
    return routine_content | habit_content


def charged(
    stored: TemplateEntryRecord,
    binding: EntryBinding | None,
    content: Mapping[tuple[BindingTarget, UUID], EntryContent],
) -> Charged | DropCause:
    """The title and the Area the block this entry becomes carries, or the cause it cannot.

    A slot carries its declared Area and no title, because nothing has been chosen to name yet. A
    concrete entry carries its content's name, and its content's Area unless the content has none,
    in which case its own declaration is what the minutes are charged to.
    """
    if stored.kind is not TemplateEntryKind.CONCRETE:
        return Charged(area_id=_an_area_a_slot_declares(stored))
    if binding is None:
        raise EntryPairingRejected(
            f"template entry {stored.id} is concrete and names no content: the table's "
            "'kind_states_its_binding' constraint pairs a concrete entry with a binding, so a row "
            "without one was not written through the schema"
        )
    found = content.get((binding.target, binding.entity_id))
    if found is None:
        return DropCause.CONTENT_THIS_TENANT_DOES_NOT_HAVE
    area_id = found.area_id or stored.area_id
    if area_id is None:
        return DropCause.CONTENT_WITH_NO_AREA_AND_NONE_DECLARED
    return Charged(area_id=area_id, title=_a_name_a_block_can_render(stored, found))


def report(dropped: Sequence[DropCause]) -> None:
    """Say once how many entries an assembly dropped, and per cause.

    Counted rather than named one line per entry, which is how a template every date shares turns
    one malformed row into seven log lines.
    """
    if not dropped:
        return
    counted = {cause.value: dropped.count(cause) for cause in sorted(set(dropped))}
    _log.warning(
        "plans.assembly.template_entry_unresolved",
        entries_dropped=len(dropped),
        by_cause=counted,
    )


def _an_area_a_slot_declares(stored: TemplateEntryRecord) -> AreaId:
    if stored.area_id is None:
        raise EntryPairingRejected(
            f"template entry {stored.id} is a slot and declares no Area: the table's "
            "'kind_states_its_binding' constraint requires one, and a slot is a duration OF an "
            "Area with its content bound late"
        )
    return stored.area_id


def _a_name_a_block_can_render(stored: TemplateEntryRecord, found: EntryContent) -> str:
    if not found.title:
        raise EntryPairingRejected(
            f"the content template entry {stored.id} names carries no title: a block renders the "
            "resolved content name, and the routine and habit boundaries each require one, so an "
            "empty title was not written through the api"
        )
    return found.title
