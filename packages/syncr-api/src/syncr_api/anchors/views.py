"""The composed answers the anchor routes hand back, and the one function that assembles them.

An anchor on its own does not answer what a detail panel asks. The panel's whole job is to say
where this commitment came from and that syncr does not own it, so the source's name and the
read-only statement travel WITH the anchor rather than being assembled by whichever caller
happens to need them. :func:`anchor_view` is that assembly, and it is a pure function of three
already-read values so a test can build one without a database.

``casts`` is what the anchor's type declares, which is empty for an untyped anchor. That is the
answer stated rather than left to be inferred from a null type identifier: an untyped anchor is
opaque busy time with no shadow of any kind, and a reader has to be able to ask.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.anchors.config import READ_ONLY_STATEMENT
from syncr_api.anchors.records import ShadowDeclaration

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from syncr_api.anchors.records import AnchorRecord, AnchorTypeRecord
    from syncr_api.calendars.records import CalendarSourceRecord
    from syncr_domain.identifiers import AnchorId


@dataclass(frozen=True, slots=True)
class AnchorView:
    """One anchor, with everything a detail panel states about it."""

    anchor: AnchorRecord
    source_name: str
    read_only_statement: str
    anchor_type: AnchorTypeRecord | None
    casts: ShadowDeclaration


@dataclass(frozen=True, slots=True)
class AnchorPage:
    """One page of composed anchors in a span, and the cursor that reaches the next one."""

    views: tuple[AnchorView, ...]
    next_cursor: tuple[datetime, AnchorId] | None


@dataclass(frozen=True, slots=True)
class Retyped:
    """The occurrence the caller named, and how many occurrences of its series moved with it."""

    view: AnchorView
    occurrences_retyped: int


def anchor_view(
    anchor: AnchorRecord,
    *,
    source: CalendarSourceRecord | None,
    anchor_type: AnchorTypeRecord | None,
) -> AnchorView:
    """One anchor composed with its source's name and the type it carries.

    ``source`` is nullable only for the reader's sake. The column is a non-nullable foreign key,
    so a source always exists; falling back to the identifier rather than raising keeps the panel
    readable and says something a reader can act on either way.
    """
    named = source.display_name if source is not None else str(anchor.source_id)
    return AnchorView(
        anchor=anchor,
        source_name=named,
        read_only_statement=READ_ONLY_STATEMENT.format(source=named),
        anchor_type=anchor_type,
        casts=ShadowDeclaration.of(None if anchor_type is None else anchor_type.specification),
    )


def anchor_views(
    anchors: Iterable[AnchorRecord],
    *,
    sources: Iterable[CalendarSourceRecord],
    types: Iterable[AnchorTypeRecord],
) -> tuple[AnchorView, ...]:
    """A whole page composed from three reads rather than three reads per anchor.

    Both collections are bounded by what a person declares -- a handful of calendars and at most a
    hundred types -- so indexing them costs less than one extra query would, and a page of two
    hundred commitments stays three reads however long it is.
    """
    by_source = {source.id: source for source in sources}
    by_type = {anchor_type.id: anchor_type for anchor_type in types}
    return tuple(
        anchor_view(
            anchor,
            source=by_source.get(anchor.source_id),
            anchor_type=None
            if anchor.anchor_type_id is None
            else by_type.get(anchor.anchor_type_id),
        )
        for anchor in anchors
    )
