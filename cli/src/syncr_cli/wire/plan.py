"""One week's stored plan, as the ledger reads it: the blocks, and the gaps that are explained.

Only the members the ledger prints are read. A response carries more than that -- each block's
binding, its reason record, its superseded placement -- and reading a member this package does
not render would be a claim about the contract that nothing here needs to make.

**A forbidden window is a row, not an omission.** It is printed so the gap is explained, and it
is visibly not a block because it has no Area. That is the whole reason it appears.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self
from uuid import UUID

from syncr_cli.errors import MalformedResponse
from syncr_cli.wire.reading import (
    JsonMapping,
    boolean,
    mappings,
    optional_text,
    span,
    text,
)
from syncr_domain.identity import Origin

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.intervals import Interval

# The origins the ledger names in the marker column, and the ones it deliberately leaves blank.
# Two sets rather than one, so the partition is assertable against the vocabulary: an origin that
# is in neither is a word this package would print nothing for without noticing.
MARKED_ORIGINS = frozenset({Origin.PREP, Origin.TRANSIT, Origin.ANCHOR})
UNMARKED_ORIGINS = frozenset({Origin.FRAME, Origin.TEMPLATE_ENTRY, Origin.HABIT, Origin.TASK})

# The marker a forbidden window carries. Not an `Origin`: a window is not a block, and giving it
# a member of the block vocabulary is how the two would come to be treated as one.
FORBIDDEN_MARKER = "forbidden"
PINNED_MARKER = "pinned"
CONFLICT_MARKER = "CONFLICT"

# What the Area column holds for a row that is charged to no Area: the frame, an imported anchor,
# and every forbidden window. One defines how much time exists and the others are time the
# product does not own.
NO_AREA = "--"


@dataclass(frozen=True, slots=True)
class Entry:
    """One row of a day: a block, or a forbidden window drawn as one.

    Both kinds are rendered by one code path because the ledger is one column layout. The
    difference a reader sees is the Area and the marker, which is exactly the difference that
    matters: a window has neither an Area nor a title of its own making.
    """

    interval: Interval
    minutes: int
    area_id: UUID | None
    title: str
    markers: tuple[str, ...]

    @property
    def start(self) -> datetime:
        return self.interval.start


@dataclass(frozen=True, slots=True)
class Block:
    """One thing that happens in the week."""

    id: str
    interval: Interval
    origin: str
    title: str
    area_id: UUID | None
    pinned: bool

    @classmethod
    def read(cls, payload: JsonMapping, path: str) -> Self:
        return cls(
            id=text(payload, "id", path),
            interval=span(payload, "interval", path),
            origin=text(payload, "origin", path),
            title=text(payload, "title", path),
            area_id=_optional_id(payload, "areaId", path),
            pinned=boolean(payload, "pinned", path),
        )

    def as_entry(self, *, conflicted: bool) -> Entry:
        markers = []
        if self.origin in MARKED_ORIGINS:
            markers.append(self.origin)
        if self.pinned:
            markers.append(PINNED_MARKER)
        if conflicted:
            markers.append(CONFLICT_MARKER)
        return Entry(
            interval=self.interval,
            minutes=self.interval.total_minutes(),
            area_id=self.area_id,
            title=self.title,
            markers=tuple(markers),
        )


@dataclass(frozen=True, slots=True)
class ForbiddenWindow:
    """A span work is forbidden in, printed so the gap it leaves is explained."""

    interval: Interval
    label: str

    @classmethod
    def read(cls, payload: JsonMapping, path: str) -> Self:
        return cls(interval=span(payload, "interval", path), label=text(payload, "label", path))

    def as_entry(self) -> Entry:
        return Entry(
            interval=self.interval,
            minutes=self.interval.total_minutes(),
            area_id=None,
            title=self.label,
            markers=(FORBIDDEN_MARKER,),
        )


@dataclass(frozen=True, slots=True)
class PlanDocument:
    """The blocks a week holds and the windows that explain its gaps."""

    blocks: tuple[Block, ...]
    forbidden_windows: tuple[ForbiddenWindow, ...]

    @classmethod
    def read(cls, payload: JsonMapping, path: str) -> Self:
        return cls(
            blocks=tuple(
                Block.read(entry, f"{path}.blocks[{index}]")
                for index, entry in enumerate(mappings(payload, "blocks", path))
            ),
            forbidden_windows=tuple(
                ForbiddenWindow.read(entry, f"{path}.forbiddenWindows[{index}]")
                for index, entry in enumerate(mappings(payload, "forbiddenWindows", path))
            ),
        )

    def entries(self, *, conflicted_block_ids: frozenset[str]) -> tuple[Entry, ...]:
        """Every row this document contributes, in start order.

        Ties are broken by the end and then by the title, so two rows that begin together are
        ordered by something the payload states rather than by the order it happened to arrive
        in. That is what makes two reads of one week diff to nothing.
        """
        rows = [
            *(block.as_entry(conflicted=block.id in conflicted_block_ids) for block in self.blocks),
            *(window.as_entry() for window in self.forbidden_windows),
        ]
        return tuple(
            sorted(rows, key=lambda row: (row.interval.start, row.interval.end, row.title))
        )


def _optional_id(payload: JsonMapping, name: str, path: str) -> UUID | None:
    """An identifier member, or null.

    A value that is neither is refused rather than read as null. Null means "charged to no
    Area", which is what makes a forbidden window visibly not a block, so answering it for an
    identifier that merely could not be parsed would print a false statement about the row.
    """
    raw = optional_text(payload, name, path)
    if raw is None:
        return None
    try:
        return UUID(raw)
    except ValueError as error:
        raise MalformedResponse(
            f"{path}.{name} is {raw!r}, which is not an identifier. Nothing was changed."
        ) from error
