"""The changes a plan may not make without assent, as one value.

syncr may add, but it may never move or remove without permission. A candidate plan therefore
splits into changes that apply on their own and changes that wait, and this module holds the
second half: what waits, in the shape the pending slot stores and the grid renders proposal
targets from.

## A change names a block, and derives its identity the way a block does

``BlockChange`` carries the week and the binding rather than an id, for the reason
:class:`syncr_domain.plan.Block` does: an id that can be supplied can be supplied wrongly, and
six mechanisms pair on this one. So there is no field to set and no argument to pass, and a
change and the block it names cannot come to disagree about which block that is.

## Which list a change is in is what kind of change it is

There is no ``kind`` field, because the three lists already say it and a field beside them could
contradict them. What each list means is a rule about the pair of intervals a change carries, and
the diff enforces all three: an addition has no before, a removal has no after, and a move has
both and they differ. A move that moves nothing is not a move, and a removal carrying an after
would render a target nobody proposed.

## One week, and one appearance per block

A diff is the difference between two documents of one week, so every change in it belongs to that
week: an id is derived against the week, so a change from another one names a block this diff
cannot be paired against. And one block appears once in the whole diff rather than once per list,
because two changes naming one block would leave the reader of the pair to decide which of them
the plan is actually proposing.

Neither rule needs a week field to state it. The members agree with each other or they do not,
and an empty diff proposes nothing about any week.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.errors import DomainError
from syncr_domain.identity import block_id

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_domain.identifiers import AreaId
    from syncr_domain.identity import BindingRef, BlockId
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import Block
    from syncr_domain.reasons import ReasonRecord
    from syncr_domain.weeks import IsoWeek


class ProposalError(DomainError):
    """A proposed change, or a set of them, breaks a rule that makes the pair readable."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BlockChange:
    """One block a candidate plan wants to add, drop, or move, and why.

    ``before`` is where the block is in the live plan and ``after`` is where the candidate wants
    it. One of the two is ``None`` for an addition or a removal, and which one is a property of
    the list this change is in.

    ``reason`` is why the CANDIDATE wants the change, taken from the candidate's own block. A
    removal has no candidate block, so its reason is the live block's: what the plan says about a
    block it is about to drop is the last thing it said about it.
    """

    iso_week: IsoWeek
    binding: BindingRef
    title: str
    area_id: AreaId | None
    reason: ReasonRecord
    before: Interval | None = None
    after: Interval | None = None

    @property
    def block_id(self) -> BlockId:
        """The block this change names, derived on every read from the week and the binding."""
        return block_id(self.iso_week, self.binding)

    @classmethod
    def added(cls, block: Block) -> BlockChange:
        """``block`` as a change that puts it somewhere it displaces something."""
        return cls(
            iso_week=block.iso_week,
            binding=block.binding,
            title=block.title,
            area_id=block.area_id,
            reason=block.reason,
            after=block.interval,
        )

    @classmethod
    def removed(cls, block: Block) -> BlockChange:
        """``block`` as a change that drops it, described by what the live plan holds."""
        return cls(
            iso_week=block.iso_week,
            binding=block.binding,
            title=block.title,
            area_id=block.area_id,
            reason=block.reason,
            before=block.interval,
        )

    @classmethod
    def moved(cls, *, live: Block, candidate: Block) -> BlockChange:
        """One block at two placements, described by what the candidate wants it to be.

        The pair has to be one block, which is what the shared identity says. A change built from
        two different blocks would render one title over another's placement.
        """
        if live.id != candidate.id:
            raise ProposalError(
                f"a move is one block at two placements, and {live.binding.kind.value!r} "
                f"{live.binding.entity_id} is not the same block as "
                f"{candidate.binding.kind.value!r} {candidate.binding.entity_id}: a change built "
                "from two blocks would render one block's title over another's placement"
            )
        return cls(
            iso_week=candidate.iso_week,
            binding=candidate.binding,
            title=candidate.title,
            area_id=candidate.area_id,
            reason=candidate.reason,
            before=live.interval,
            after=candidate.interval,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProposalDiff:
    """The assent-requiring changes between the live plan and a candidate plan.

    Crosses the api boundary and is stored in the pending slot, so it is the one statement of
    what a proposal is asking for. A diff that is empty is asking for nothing, which is a state
    with a consequence: nothing is held for assent and nothing is replaced.
    """

    added: tuple[BlockChange, ...] = ()
    removed: tuple[BlockChange, ...] = ()
    moved: tuple[BlockChange, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "added", tuple(self.added))
        object.__setattr__(self, "removed", tuple(self.removed))
        object.__setattr__(self, "moved", tuple(self.moved))
        for change in self.added:
            _require_placements(change, replaces=False, wants=True, spelled="an addition")
        for change in self.removed:
            _require_placements(change, replaces=True, wants=False, spelled="a removal")
        for change in self.moved:
            _require_placements(change, replaces=True, wants=True, spelled="a move")
            _require_a_placement_that_moved(change)
        _require_one_week(self.changes())
        _require_one_appearance_per_block(self.changes())

    def is_empty(self) -> bool:
        """Whether this diff asks for nothing at all."""
        return not (self.added or self.removed or self.moved)

    def changes(self) -> Iterator[BlockChange]:
        """Every change this diff holds, whichever list it is in."""
        yield from self.added
        yield from self.removed
        yield from self.moved


def _require_placements(change: BlockChange, *, replaces: bool, wants: bool, spelled: str) -> None:
    """The pair of placements a change carries has to match the list it is in.

    Both directions, because both produce a fiction. An addition carrying a placement it replaces
    states that the candidate is moving a block the live plan does not hold there, and a move
    missing one renders half an arrow.
    """
    wrong = [
        f"{'carries' if carried else 'states no'} {name}"
        for name, carried, required in (
            ("placement it replaces", change.before is not None, replaces),
            ("placement it wants", change.after is not None, wants),
        )
        if carried != required
    ]
    if not wrong:
        return
    raise ProposalError(
        f"{spelled} of {change.title!r} {' and '.join(wrong)}: which of the two a change carries "
        "is what its list means, so a change disagreeing with its list describes something else"
    )


def _require_a_placement_that_moved(change: BlockChange) -> None:
    """A move whose placements are equal is not a move.

    It would ask the user to assent to nothing, and it is exactly what an unchanged block looks
    like, so admitting one would make every re-solve of an untouched week ask for approval.
    """
    if change.before != change.after:
        return
    raise ProposalError(
        f"the move of {change.title!r} leaves it where it is: a change asking for assent to "
        "nothing is what an unchanged block looks like, so it is not a change at all"
    )


def _require_one_week(changes: Iterator[BlockChange]) -> None:
    """One week per diff, because an id is derived against the week it is in."""
    weeks = sorted({str(change.iso_week) for change in changes})
    if len(weeks) <= 1:
        return
    raise ProposalError(
        f"a proposal diff is the difference between two documents of one week, and this one "
        f"names {', '.join(weeks)}: an id is derived against the week, so a change from another "
        "one names a block this diff cannot be paired against"
    )


def _require_one_appearance_per_block(changes: Iterator[BlockChange]) -> None:
    """One appearance per block across all three lists, so the pair is unambiguous."""
    seen: set[BlockId] = set()
    for change in changes:
        if change.block_id in seen:
            raise ProposalError(
                f"{change.title!r} appears twice in one proposal diff: two changes naming one "
                "block leave the reader to decide which of them the plan is proposing, and it "
                "is proposing one thing per block"
            )
        seen.add(change.block_id)
