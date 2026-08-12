"""What a concrete template entry becomes: the name its block carries, and the Area it charges.

A block carries the resolved content name and, unless it is the frame or an anchor, an Area. An
entry declares neither: it names a routine or a habit, and both live in tables with no shared
parent. This module resolves that pair against those rows, so the snapshot carries an entry only
when a block can be built from it.

**The resolution happens here rather than in the snapshot** because no join inside the snapshot is
total: a habit's occurrences are cadence-filtered, so an entry naming a habit that is not due this
week would find no name at all.

## The frame is the authority for a routine's placement

A routine is already placed on every date its frame is not declared off, so an entry naming one
restates a fact the frame has already answered. It is not charged and it produces no block:
:data:`PLACED_BY_THE_FRAME` is what the resolution answers, the routine's minutes stay the frame's,
and an Area the entry declares is a label rather than a charge. A second block would put the same
content on one date twice and subtract one routine's minutes from the week twice, which contradicts
the frame defining how much time exists. The boundary states this to the author when the entry is
written, in :data:`THE_FRAME_PLACES_A_ROUTINE`, so a declaration nothing places is not silently
ignored.

## One state is dropped and three are refused, and the difference is what the table allows

:class:`DropCause` names a binding naming no row this tenant has, which is a producer defect the
template boundary does not yet refuse. Dropping is the degradation an anchor carrying an unread
type already takes: the rest of the week assembles, and refusing would fail every solve, pin and
live verdict for the week over one row.

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
from typing import TYPE_CHECKING, Final

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
    """Why an entry a week holds cannot become a block, counted per cause in the log line.

    ``CONTENT_THIS_TENANT_DOES_NOT_HAVE`` is the reachable one: a binding naming no row, in either
    table.

    ``CONTENT_WITH_NO_AREA_AND_NONE_DECLARED`` is a net rather than a live cause. It answers content
    that resolves with no Area of its own beside an entry that declares none, and no table can hold
    that pair today: a habit's Area column is ``NOT NULL``, and a routine has no Area but is placed
    by the frame before an Area is read for it at all. It stays because it costs no migration and
    because a widened content mapping would reach it before anyone rediscovered the state, so a
    check keyed on it is checking a state nothing currently produces.
    """

    CONTENT_THIS_TENANT_DOES_NOT_HAVE = "content_this_tenant_does_not_have"
    CONTENT_WITH_NO_AREA_AND_NONE_DECLARED = "content_with_no_area_and_none_declared"


@dataclass(frozen=True, slots=True)
class EntryContent:
    """What a concrete entry's binding names: the title a block carries, and its Area.

    A routine has no Area, because the frame is not a category competing with Fitness, and nothing
    supplies one on its behalf: the frame places the routine and no Area is charged for it.
    """

    title: str
    area_id: AreaId | None = None


@dataclass(frozen=True, slots=True)
class PlacedByTheFrame:
    """The frame is the authority for this entry's placement, so the entry places nothing.

    A distinct answer from a drop and from an off-plan suppression: nothing is wrong with the row,
    nothing is lost, and no count of producer defects should move because of it.
    """


PLACED_BY_THE_FRAME: Final = PlacedByTheFrame()

THE_FRAME_PLACES_A_ROUTINE: Final = (
    "The frame is the authority for a routine's placement. This routine is already placed at its "
    "own target time on every date you have not declared off, so the time named here places "
    "nothing and no second block appears. An Area named here is a label rather than a charge: the "
    "routine's minutes belong to the frame and no Area is charged for them. Change the routine "
    "itself to move it."
)


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
) -> Charged | PlacedByTheFrame | DropCause:
    """The title and the Area the block this entry becomes carries, or why it becomes none.

    A slot carries its declared Area and no title, because nothing has been chosen to name yet. A
    concrete entry carries its content's name and its content's Area, falling back to its own
    declaration.

    **The frame is the authority for a routine's placement**, so an entry naming a routine this
    tenant holds is answered by :data:`PLACED_BY_THE_FRAME` before an Area or a title is resolved
    for it: neither is read, because no block is built. A binding naming a routine the tenant does
    not hold is still a drop, because a dangling binding is a defect whichever table it names.
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
    if binding.target is BindingTarget.ROUTINE:
        return PLACED_BY_THE_FRAME
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
