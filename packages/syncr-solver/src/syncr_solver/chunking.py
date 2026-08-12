"""How a divided task's pieces are numbered, and the one thing placement cannot decide.

A task placed in pieces raises two questions, and this module answers the first of them.

**Which piece of the division is this?** An identity. A block's id is derived from its binding and
``split_index`` is part of that binding, so a pin names a block id and renumbering a chunk renames
the block the pin points at. ``split_count`` travels with the number because the domain refuses a
chunk numbered at or above the count it states: the count is what makes the number nameable.

**How many pieces is a reader told about?** A label, decided where the other rendered strings are
and not held by either field here. A pin on a high chunk is what separates the two: three pieces
numbered 0, 1 and 5 store a count of six, so a count read as a label says "of six" for a week that
holds three pieces. Where the numbers run from zero with no gap the two figures coincide, which is
every division a solve places on its own.

The identity is settled in two halves that run at two different moments.

## As a piece is placed: the lowest number no piece of that task has taken

Lowest rather than next, so a pin holding chunk 2 does not push the pieces a solve places around it
to 3 and 4, and so re-placing one task twice in a search produces the same numbers. **A piece
carrying no number occupies number zero**, because one chunk is the whole task and the domain spells
that by carrying no number at all: read as unoccupied, a piece placed beside such a block would
derive the same identity and the document would refuse the pair.

## When the document is built: the FIRST piece gains number zero, once a second exists

Most tasks are placed whole, so the first piece carries no number and a second piece starts at one.
That is the one thing placement cannot know, and it is the only adjustment the document build makes.
An inherited block is never renumbered: rewriting a pinned chunk's binding would change its id, and
the pin would stop naming the block it pins. It keeps the count it arrived with too, so a pin can
leave one piece of a division stating a higher count than the pieces beside it.

The count a placed piece states is one above the highest number the division occupies, floored at
the fewest chunks a division can have. That is the whole rule: a count below the highest number in
use names a chunk that does not exist and the domain refuses the document.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from syncr_domain.identity import BindingKind, BindingRef
from syncr_domain.plan import MIN_SPLIT_COUNT
from syncr_solver.reading import demand_key

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.identity import BindingRef as Binding
    from syncr_domain.plan import Block
    from syncr_solver.attempt import Placed
    from syncr_solver.reading import DemandKey


def chunk_ordinal(placements: Sequence[Placed], binding: Binding) -> int:
    """The number the next piece of this task takes: the lowest no piece of it has taken."""
    wanted = demand_key(binding)
    taken = {
        0 if held.block.binding.split_index is None else held.block.binding.split_index
        for held in placements
        if demand_key(held.block.binding) == wanted
    }
    ordinal = 0
    while ordinal in taken:
        ordinal += 1
    return ordinal


def numbered(placements: Sequence[Placed]) -> tuple[Block, ...]:
    """These blocks as a document holds them, with each division's numbers settled."""
    pieces = _pieces_per_task(placements)
    highest = _highest_chunk(placements)
    return tuple(_renumbered(held, pieces, highest) for held in placements)


def _pieces_per_task(placements: Sequence[Placed]) -> Mapping[DemandKey, int]:
    found: dict[DemandKey, int] = {}
    for held in placements:
        if held.block.binding.kind is not BindingKind.TASK:
            continue
        key = demand_key(held.block.binding)
        found[key] = found.get(key, 0) + 1
    return found


def _highest_chunk(placements: Sequence[Placed]) -> Mapping[DemandKey, int]:
    found: dict[DemandKey, int] = {}
    for held in placements:
        index = held.block.binding.split_index
        if index is None:
            continue
        key = demand_key(held.block.binding)
        found[key] = max(found.get(key, 0), index)
    return found


def _renumbered(
    held: Placed, pieces: Mapping[DemandKey, int], highest: Mapping[DemandKey, int]
) -> Block:
    """One block, numbered where the task turned out to be divided and left alone where not.

    A task the solve holds one piece of is returned unchanged, and that is the whole of the
    undivided case: such a piece carries no number, because a number is issued only when
    :func:`chunk_ordinal` finds zero already taken, which needs a second piece of the same task.
    Dropping a number here would therefore be unreachable code, and a raise-probe confirmed it.
    """
    block = held.block
    if not held.chosen or block.binding.kind is not BindingKind.TASK:
        return block
    key = demand_key(block.binding)
    if pieces.get(key, 0) < MIN_SPLIT_COUNT:
        return block
    return replace(
        block,
        binding=BindingRef.for_task(
            block.binding.entity_id, split_index=block.binding.split_index or 0
        ),
        split_count=max(MIN_SPLIT_COUNT, highest.get(key, 0) + 1),
    )
