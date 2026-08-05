"""What a template entry's block is called and charged to, driven directly rather than by a week.

These are the states the assembler cannot reach through its fakes without a whole week of
declarations, and the reason they can be driven at all is that the resolution returns its answer
instead of appending to a caller's list.

Three of them are refusals rather than drops, and the distinction is what the tables allow. A slot
with no Area and a concrete entry with no binding are forbidden by ``kind_states_its_binding``, and
an empty content title is forbidden by the routine and habit boundaries. A drop cause an operator
can never see would be worse than no cause, so those raise where they can name the row instead.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import time
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from syncr_api.plans.entry_content import (
    Charged,
    DropCause,
    EntryPairingRejected,
    charged,
    content_by_binding,
)
from syncr_domain.templates import BindingTarget, EntrySpan, TemplateEntryKind
from syncr_solver.inputs import EntryBinding
from tests.assembly_fakes import a_concrete_entry, a_habit, a_routine, a_slot_entry, an_area

if TYPE_CHECKING:
    from syncr_api.templates.records import TemplateEntryRecord


def a_binding(target: BindingTarget, entity_id: UUID | None = None) -> EntryBinding:
    return EntryBinding(target=target, entity_id=entity_id or uuid4())


def test_a_habit_backed_entry_is_charged_to_the_habit_s_area_and_named_by_the_habit() -> None:
    area = an_area()
    habit = a_habit(area_id=area.id, title="Shower")
    entry = a_concrete_entry(template_id=uuid4(), target=BindingTarget.HABIT, entity_id=habit.id)
    binding = EntryBinding(target=BindingTarget.HABIT, entity_id=habit.id)

    resolved = charged(entry, binding, content_by_binding([], [habit]))

    assert resolved == Charged(area_id=area.id, title="Shower")


def test_a_routine_backed_entry_is_charged_to_the_area_the_entry_declares() -> None:
    area = an_area()
    routine = a_routine(title="Wake")
    entry = a_concrete_entry(
        template_id=uuid4(),
        target=BindingTarget.ROUTINE,
        entity_id=routine.id,
        area_id=area.id,
    )
    binding = EntryBinding(target=BindingTarget.ROUTINE, entity_id=routine.id)

    resolved = charged(entry, binding, content_by_binding([routine], []))

    assert resolved == Charged(area_id=area.id, title="Wake")


def test_a_slot_carries_its_declared_area_and_no_name() -> None:
    area = an_area()
    entry = a_slot_entry(template_id=uuid4(), area_id=area.id)

    assert charged(entry, None, {}) == Charged(area_id=area.id, title=None)


def test_content_this_tenant_does_not_have_is_a_drop_rather_than_a_refusal() -> None:
    # The template boundary does not resolve a binding yet, so this is a state a stored row really
    # holds, and the week has to assemble without that part of the day shape.
    entry = a_concrete_entry(template_id=uuid4(), target=BindingTarget.HABIT, entity_id=uuid4())

    assert charged(entry, a_binding(BindingTarget.HABIT), {}) is (
        DropCause.CONTENT_THIS_TENANT_DOES_NOT_HAVE
    )


def test_a_routine_backed_entry_declaring_no_area_is_a_drop_rather_than_a_refusal() -> None:
    # Neither side can name an Area: a routine has none, because the frame is not a category
    # competing with Fitness, and the entry declared none of its own.
    routine = a_routine()
    entry = a_concrete_entry(
        template_id=uuid4(), target=BindingTarget.ROUTINE, entity_id=routine.id
    )
    binding = EntryBinding(target=BindingTarget.ROUTINE, entity_id=routine.id)

    assert charged(entry, binding, content_by_binding([routine], [])) is (
        DropCause.CONTENT_WITH_NO_AREA_AND_NONE_DECLARED
    )


def test_a_binding_resolves_only_in_the_table_its_target_names() -> None:
    # Two rows sharing an identifier would otherwise resolve to whichever table was looked in first,
    # which is the whole reason the target column exists.
    routine = a_routine()
    entry = a_concrete_entry(template_id=uuid4(), target=BindingTarget.HABIT, entity_id=routine.id)
    binding = EntryBinding(target=BindingTarget.HABIT, entity_id=routine.id)

    assert charged(entry, binding, content_by_binding([routine], [])) is (
        DropCause.CONTENT_THIS_TENANT_DOES_NOT_HAVE
    )


def test_a_slot_with_no_area_is_refused_because_its_table_forbids_the_row() -> None:
    entry = a_slot_entry(template_id=uuid4(), area_id=uuid4())
    forbidden = _replaced(entry, area_id=None)

    with pytest.raises(EntryPairingRejected, match="declares no Area"):
        charged(forbidden, None, {})


def test_a_concrete_entry_with_no_binding_is_refused_for_the_same_reason() -> None:
    entry = a_concrete_entry(template_id=uuid4(), area_id=uuid4())

    with pytest.raises(EntryPairingRejected, match="names no content"):
        charged(entry, None, {})


def test_content_carrying_an_empty_title_is_refused_where_the_row_can_be_named() -> None:
    # The one path where a malformed row fails the whole week rather than losing one entry, and the
    # trade is deliberate: a block renders the resolved content name, both boundaries require one,
    # so an empty title was written outside the api and the refusal says which row carries it.
    area = an_area()
    habit = a_habit(area_id=area.id, title="")
    entry = a_concrete_entry(template_id=uuid4(), target=BindingTarget.HABIT, entity_id=habit.id)
    binding = EntryBinding(target=BindingTarget.HABIT, entity_id=habit.id)

    with pytest.raises(EntryPairingRejected, match="carries no title"):
        charged(entry, binding, content_by_binding([], [habit]))


def test_every_drop_cause_is_a_state_a_stored_row_can_hold() -> None:
    # The vocabulary bounded by the inventory of what may exist. Each member is produced by one of
    # the cases above, so a cause with no reachable state cannot be added without a test for it.
    routine = a_routine()
    reachable = {
        charged(
            a_concrete_entry(template_id=uuid4(), target=BindingTarget.HABIT, entity_id=uuid4()),
            a_binding(BindingTarget.HABIT),
            {},
        ),
        charged(
            a_concrete_entry(
                template_id=uuid4(), target=BindingTarget.ROUTINE, entity_id=routine.id
            ),
            EntryBinding(target=BindingTarget.ROUTINE, entity_id=routine.id),
            content_by_binding([routine], []),
        ),
    }

    assert reachable == set(DropCause)


def _replaced(entry: TemplateEntryRecord, *, area_id: UUID | None) -> TemplateEntryRecord:
    """A stored entry with one column rewritten, for a state the table itself forbids."""
    return replace(entry, area_id=area_id)


def test_the_span_a_fake_entry_carries_is_a_real_declaration() -> None:
    # The control for the refusals above: they are driven through records the same constructors the
    # repository uses accept, so none of them passes because its fixture was already malformed.
    assert a_slot_entry(template_id=uuid4(), area_id=uuid4()).span == EntrySpan(
        target_time=time(18, 0), duration_minutes=60, flex_band_minutes=15
    )
    assert a_concrete_entry(template_id=uuid4()).kind is TemplateEntryKind.CONCRETE
