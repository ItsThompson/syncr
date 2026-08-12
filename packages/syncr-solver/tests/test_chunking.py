"""The two numbers a divided task's pieces carry, and which of them a pin can pull apart.

Every case places pieces of one task and reads the pair the document stores against each. They
differ in one input: what the week already holds at a chunk number the solve would not have reached.

The dense case is the pair a solve produces on its own, where the number the pieces reach and the
number of pieces are the same figure. The sparse cases are the ones a pin creates, where they are
six and three, so an assertion over either can tell which of the two a stored count is.

Every figure asserted below is a literal rather than a value read back off the week that produced
it, so a fixture moved here reddens instead of travelling into the expectation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from syncr_domain.identity import TASK_OCCURRENCE_KEY, BindingKind, BindingRef
from tests.materialized_weeks import a_frame_entry, a_live_plan, a_pin, an_area_budget, between
from tests.objective_weeks import A_TASK, a_chunk_block, an_eligible_task
from tests.solve_weeks import a_week, blocks_titled, minutes_toward, solved

if TYPE_CHECKING:
    from syncr_domain.plan import Block, PlanDocument
    from syncr_solver.inputs import SolveInputs

PINNED_CHUNK = BindingRef.for_task(A_TASK, split_index=5)
THE_PINNED_HOUR = between(9, 10)
WHERE_THE_PIN_CAME_FROM = between(14, 15)


def _a_week_of_three_gaps(**overrides: Any) -> SolveInputs:
    """One hour on its own, then two two-hour gaps, all on Monday and all ahead of ``now``.

    The hour is what a pinned piece occupies, so the work the solve places has exactly the two
    longer gaps to take and the division it produces is decided by the week rather than by how much
    the packer feels like taking.
    """
    return a_week(
        frame=(
            a_frame_entry(day=0, interval=between(0, 9)),
            a_frame_entry(day=0, interval=between(10, 14)),
            a_frame_entry(day=0, interval=between(16, 19)),
            a_frame_entry(day=0, interval=between(21, 24)),
            *(a_frame_entry(day=day, interval=between(0, 24, day=day)) for day in range(1, 7)),
        ),
        areas=(an_area_budget(target_minutes=600),),
        **overrides,
    )


def _a_week_holding_the_pinned_chunk(held: Block, **overrides: Any) -> SolveInputs:
    """The same week, with one piece of the task pinned where the user dragged it.

    The pin states what it replaced and what replacing it cost, which is what makes the block read
    as the user's own placement rather than as one the solve happened to keep.
    """
    return _a_week_of_three_gaps(
        live_plan=a_live_plan(held),
        pins=(
            a_pin(
                binding=PINNED_CHUNK,
                interval=THE_PINNED_HOUR,
                superseded_placement=WHERE_THE_PIN_CAME_FROM,
                objective_delta=0.25,
            ),
        ),
        **overrides,
    )


def _pieces_in(document: PlanDocument) -> tuple[Block, ...]:
    return blocks_titled(document, "Leetcode")


def test_a_pin_on_a_high_chunk_stores_the_count_the_numbers_reach_and_not_the_pieces_held() -> None:
    """Three pieces, one of them chunk five, so the stored count is six while three pieces exist.

    The stored pair answers which piece of the division this is, and the count is what makes the
    index nameable: a document holding chunk five states a count above five or the domain refuses
    it. What a reader is shown is the other question, and it is not this field.
    """
    held_before = a_chunk_block(index=5, of=6, interval=THE_PINNED_HOUR)
    week = _a_week_holding_the_pinned_chunk(
        held_before,
        eligible_tasks=(an_eligible_task(remaining_minutes=240, min_chunk_minutes=60),),
    )

    document = solved(week).document
    pieces = _pieces_in(document)
    pinned_after = next(piece for piece in pieces if piece.split_index == 5)

    assert len(pieces) == 3
    assert {piece.split_index for piece in pieces} == {0, 1, 5}
    assert {piece.split_count for piece in pieces} == {6}
    assert minutes_toward(document, A_TASK) == 300
    # The pin still names the block it pins: the binding it was stored against, component by
    # component, and the id that binding derives.
    assert pinned_after.binding == held_before.binding
    assert (
        pinned_after.binding.kind,
        pinned_after.binding.entity_id,
        pinned_after.binding.occurrence_key,
        pinned_after.binding.split_index,
    ) == (BindingKind.TASK, A_TASK, TASK_OCCURRENCE_KEY, 5)
    assert pinned_after.id == held_before.id
    assert (pinned_after.interval, pinned_after.pinned) == (THE_PINNED_HOUR, True)


def test_a_division_the_solve_places_alone_stores_a_count_equal_to_its_pieces() -> None:
    """The same week with nothing pinned: three pieces numbered from zero, so the count is three.

    The mirror of the case above and the control that keys its six to the chunk the pin holds: where
    the numbers run from zero with no gap the two questions have one answer, so a rule storing the
    number of pieces passes here and fails there.
    """
    week = _a_week_of_three_gaps(
        eligible_tasks=(an_eligible_task(remaining_minutes=300, min_chunk_minutes=60),),
    )

    document = solved(week).document
    pieces = _pieces_in(document)

    assert len(pieces) == 3
    assert {piece.split_index for piece in pieces} == {0, 1, 2}
    assert {piece.split_count for piece in pieces} == {3}
    assert minutes_toward(document, A_TASK) == 300


def test_the_piece_the_week_already_holds_counts_toward_the_division_it_belongs_to() -> None:
    """One placed piece beside the pinned chunk, and the placed one carries a number.

    Two pieces are a division, so neither is the whole task: a piece placed beside a pinned chunk
    that carried no number at all would derive the same id as chunk zero and the document would
    refuse the pair. The reading that settles it counts what the week holds, not only what this
    solve chose.
    """
    week = _a_week_holding_the_pinned_chunk(
        a_chunk_block(index=5, of=6, interval=THE_PINNED_HOUR),
        eligible_tasks=(an_eligible_task(remaining_minutes=120, min_chunk_minutes=60),),
    )

    pieces = _pieces_in(solved(week).document)

    assert len(pieces) == 2
    assert {piece.split_index for piece in pieces} == {0, 5}
    assert {piece.split_count for piece in pieces} == {6}


def test_the_pinned_chunk_keeps_the_count_it_arrived_with_when_the_pieces_reach_lower() -> None:
    """A pin from a division of eight, re-solved into three pieces: it still states eight.

    An inherited block is not rewritten, because rewriting its binding would change its id and the
    pin would stop naming the block it pins. So the count is per block and a pin can leave one piece
    of a division stating a higher count than the pieces beside it, which is why what a reader is
    shown cannot be read off one block's own field.
    """
    held_before = a_chunk_block(index=5, of=8, interval=THE_PINNED_HOUR)
    week = _a_week_holding_the_pinned_chunk(
        held_before,
        eligible_tasks=(an_eligible_task(remaining_minutes=240, min_chunk_minutes=60),),
    )

    pieces = _pieces_in(solved(week).document)
    pinned_after = next(piece for piece in pieces if piece.split_index == 5)

    assert len(pieces) == 3
    assert {piece.split_count for piece in pieces} == {6, 8}
    assert pinned_after.split_count == 8
    assert pinned_after.binding == held_before.binding
    assert pinned_after.id == held_before.id
