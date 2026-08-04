"""Block identity: what a block holds, which instance of it, and the id that follows.

Six mechanisms match a block to another block or to a stored row: the authority
classifier's diff, pin creation, partial rejection, outcomes, edit events, and
repeated-pin promotion detection. Identity is therefore load-bearing rather than
incidental, and it is defined here once so none of the six invents a matching rule.

There are two levels, and conflating them is the mistake this module exists to prevent.
:class:`BindingRef` is CONTENT identity: what a block holds, plus which of several
instances of that content within the week. :func:`block_id` is a BLOCK's identity, and it
is a derived hash of the week and the content identity rather than a value anybody mints.

**Why the id is derived.** The classifier pairs two whole documents to decide what
auto-applies and what needs assent. An id that is a function of the week and the binding
makes "the same content" decidable from two literals with no database lookup, which is what
makes the classifier a pure function. A lookup-based fallback would undo that.

**Why an occurrence key exists.** One binding routinely produces several blocks in one week.
Seven ``Sleep`` blocks would otherwise derive one id between them, so marking Monday's
``Sleep`` partial would attach to all seven and Wednesday's shifting an hour would be
undetectable. Routines are about 40% of a week's blocks, so this is the ordinary case. The
same collision hits a concrete template entry, which materializes once per matching date,
and the two transit blocks one anchor casts.

**Why the derivation differs by kind.** A date keys blocks whose day is determined before
the solver runs; an index keys blocks the solver places. Keyed by date, dragging a habit
from Monday to Wednesday would read as a removal plus an addition rather than as the move
the user made, which is the pair the learning layer trains on. Keyed by index, changing one
weekday's day type would renumber the rest, so an outcome already recorded against the
third ``Shower`` would silently move to a different day.

**Nothing here reads text a person or a publisher wrote.** Every component comes from a
closed vocabulary this module owns: a kind, a UUID, and a key that is a local date, a
zero-padded index, a fixed literal, or one of two transit legs. No title, no label, and no
external UID reaches an id, so a re-titled anchor and a renamed habit keep the identity
they had. Bounding and scrubbing text is a boundary concern with its own home in the api,
and a second definition of a text class here would diverge from it.

A key is compared for equality and nothing else. That is why one opaque string serves every
kind rather than a union of typed discriminators, and it is why the two-digit padding is not
an ordering: past ``99`` the keys do not sort lexicographically, and nothing sorts them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING, Final, assert_never

from syncr_domain.errors import DomainError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date

type BlockId = str
"""A block's derived identity. Opaque: paired for equality, never parsed."""

# A full SHA-256 in hex. The width is the whole digest rather than a truncation because the
# column that stores one reserves exactly this much, and a shortened id would trade a
# collision risk for nothing: the value is never read by a person.
BLOCK_ID_LENGTH: Final = 64

# Separates the components of the text an id is taken over. A unit separator cannot appear
# in any component -- a kind and a leg are closed vocabularies, a UUID and a week identifier
# have fixed shapes, and a key is one of four validated forms -- so the joined text
# determines the components it was built from.
_COMPONENT_SEPARATOR: Final = "\x1f"

# `task` takes one demand per week and `split_index` distinguishes its chunks, so the key
# itself is a constant rather than a counter.
TASK_OCCURRENCE_KEY: Final = "00"

# An anchor and its prep buffer occur once each, so neither needs a discriminator.
NO_OCCURRENCE: Final = ""

# How wide a habit's occurrence index is padded. Two digits is the spelling the interface
# and the fixtures use; a third digit appears past 99 and no reader is ordered by it.
INDEX_DIGITS: Final = 2


class BindingError(DomainError):
    """A binding names a content instance its kind cannot produce."""


class Origin(StrEnum):
    """What a block IS to the reader. The vocabulary the grid and the ledger render.

    Seven members, one per kind of intent a week holds. Three are spelled differently from
    the :class:`BindingKind` that produces them, and the mapping between the two is stated
    once in this module.
    """

    FRAME = "frame"
    TEMPLATE_ENTRY = "template_entry"
    HABIT = "habit"
    TASK = "task"
    ANCHOR = "anchor"
    PREP = "prep"
    TRANSIT = "transit"


class BindingKind(StrEnum):
    """Which entity a block's content comes from, and therefore how it is keyed.

    ``template_entry`` is distinct from ``routine`` because a concrete entry and a bare
    routine are separately editable, so each needs its own identity even when the entry
    names the routine.
    """

    ROUTINE = "routine"
    TEMPLATE_ENTRY = "template_entry"
    HABIT = "habit"
    TASK = "task"
    ANCHOR = "anchor"
    ANCHOR_PREP = "anchor_prep"
    ANCHOR_TRANSIT = "anchor_transit"


class TransitLeg(StrEnum):
    """Which of an anchor's two journeys a transit block is.

    The one discriminator between ``Leave for Uni`` and ``Go Home``. Without it the two
    would derive one id between them.
    """

    OUT = "out"
    BACK = "back"


# The binding vocabulary and the origin vocabulary are two readings of the same seven cases:
# a binding names the entity, an origin names what the block is to the reader. Stated here
# in one direction only, so the inverse cannot disagree with it.
_ORIGIN_BY_KIND: Final[Mapping[BindingKind, Origin]] = {
    BindingKind.ROUTINE: Origin.FRAME,
    BindingKind.TEMPLATE_ENTRY: Origin.TEMPLATE_ENTRY,
    BindingKind.HABIT: Origin.HABIT,
    BindingKind.TASK: Origin.TASK,
    BindingKind.ANCHOR: Origin.ANCHOR,
    BindingKind.ANCHOR_PREP: Origin.PREP,
    BindingKind.ANCHOR_TRANSIT: Origin.TRANSIT,
}

_KIND_BY_ORIGIN: Final[Mapping[Origin, BindingKind]] = {
    origin: kind for kind, origin in _ORIGIN_BY_KIND.items()
}


def origin_of(kind: BindingKind) -> Origin:
    """What a block bound this way is to the reader."""
    return _ORIGIN_BY_KIND[kind]


def binding_kind_of(origin: Origin) -> BindingKind:
    """Which binding produces a block of this origin.

    The inverse is derived from the forward mapping rather than written out, so the two
    cannot drift. A suite asserts the pair is total and injective in both directions, which
    is what lets either vocabulary determine the other and neither be stored twice.
    """
    return _KIND_BY_ORIGIN[origin]


def date_occurrence_key(on: Date) -> str:
    """The key a block materializing on this local date takes.

    Read by ``routine`` and ``template_entry``, whose day is decided before the solver runs.
    """
    return on.isoformat()


def index_occurrence_key(index: int) -> str:
    """The key the ``index``-th occurrence of a habit in one week takes.

    Zero-based, and assigned by the week assembler in expansion order.
    """
    if index < 0:
        raise BindingError(
            f"an occurrence index counts from zero and this one is {index}: a habit's key "
            "is the position the assembler expanded it into, not an offset from anything"
        )
    return f"{index:0{INDEX_DIGITS}d}"


def habit_occurrence_keys(count: int) -> tuple[str, ...]:
    """The keys a habit's ``count`` occurrences take in one week, in expansion order.

    Stated here rather than at the expansion, so the ordinals a cadence produces have one
    definition. Because the keys are the leading ``count`` of one sequence, reducing a
    cadence drops the HIGHEST ordinals and re-keys none of the survivors: 4 occurrences
    keyed ``00`` to ``03`` become 3 keyed ``00`` to ``02``, and an outcome recorded against
    ``01`` still names the same occurrence.
    """
    if count < 0:
        raise BindingError(f"a habit cannot occur {count} times in a week")
    return tuple(index_occurrence_key(index) for index in range(count))


@dataclass(frozen=True, slots=True)
class BindingRef:
    """Content identity: what a block holds, and which instance of it within the week.

    Stable across re-solves by construction, because every component is either a stored
    identifier or a discriminator the assembler derives the same way every time.

    The seven named constructors are the derivation: each one takes what its kind needs and
    spells the key itself, so a caller never writes a key. The constructor validates the
    pair anyway, because a binding also arrives rebuilt from a stored document, and a key
    that does not match its kind would silently identify nothing.
    """

    kind: BindingKind
    entity_id: UUID
    occurrence_key: str
    split_index: int | None = None

    def __post_init__(self) -> None:
        _require_a_key_matching_the_kind(self.kind, self.occurrence_key)
        _require_a_split_only_a_task_can_have(self.kind, self.split_index)

    @classmethod
    def for_routine(cls, routine_id: UUID, *, on: Date) -> BindingRef:
        """One night's ``Sleep``, keyed by the local date it materializes on."""
        return cls(BindingKind.ROUTINE, routine_id, date_occurrence_key(on))

    @classmethod
    def for_template_entry(cls, entry_id: UUID, *, on: Date) -> BindingRef:
        """One day's ``Shower``, keyed by the local date the entry materializes on."""
        return cls(BindingKind.TEMPLATE_ENTRY, entry_id, date_occurrence_key(on))

    @classmethod
    def for_habit(cls, habit_id: UUID, *, index: int) -> BindingRef:
        """One of a habit's occurrences, keyed by its position in the week's expansion."""
        return cls(BindingKind.HABIT, habit_id, index_occurrence_key(index))

    @classmethod
    def for_task(cls, task_id: UUID, *, split_index: int | None = None) -> BindingRef:
        """One task's demand for the week, and which chunk of it when it was divided."""
        return cls(BindingKind.TASK, task_id, TASK_OCCURRENCE_KEY, split_index)

    @classmethod
    def for_anchor(cls, anchor_id: UUID) -> BindingRef:
        """The imported commitment itself. One per anchor, so it needs no key."""
        return cls(BindingKind.ANCHOR, anchor_id, NO_OCCURRENCE)

    @classmethod
    def for_anchor_prep(cls, anchor_id: UUID) -> BindingRef:
        """An anchor's prep block. One per anchor, so it needs no key either."""
        return cls(BindingKind.ANCHOR_PREP, anchor_id, NO_OCCURRENCE)

    @classmethod
    def for_anchor_transit(cls, anchor_id: UUID, *, leg: TransitLeg) -> BindingRef:
        """One of an anchor's two journeys, keyed by which way it goes."""
        return cls(BindingKind.ANCHOR_TRANSIT, anchor_id, leg.value)

    @property
    def origin(self) -> Origin:
        """What a block carrying this binding is to the reader."""
        return origin_of(self.kind)

    @property
    def content_key(self) -> tuple[BindingKind, UUID, int | None]:
        """This binding without the occurrence, for grouping across weeks.

        What repeated-pin promotion detection groups on: "pinned ``Gym`` to 13:00 for three
        consecutive weeks" spans weeks and occurrences, so the occurrence is what has to
        drop out. Opaque and compared for equality, like the key itself.
        """
        return (self.kind, self.entity_id, self.split_index)


def block_id(iso_week: IsoWeek, binding: BindingRef) -> BlockId:
    """The id a block holding ``binding`` in ``iso_week`` has. Derived, never minted.

    The same content instance in the same week always yields the same id, so a re-solve of
    unchanged inputs produces matching ids and two documents pair on them with no lookup.

    The digest is taken over the components joined by a separator none of them can contain,
    so distinct identities cannot produce one text. Two identities colliding on 256 bits of
    SHA-256 is not a case any input reaches.
    """
    return sha256(_identity_text(iso_week, binding).encode("utf-8")).hexdigest()


def _identity_text(iso_week: IsoWeek, binding: BindingRef) -> str:
    return _COMPONENT_SEPARATOR.join(
        (
            str(iso_week),
            binding.kind.value,
            str(binding.entity_id),
            binding.occurrence_key,
            "" if binding.split_index is None else str(binding.split_index),
        )
    )


def _require_a_key_matching_the_kind(kind: BindingKind, key: str) -> None:
    """The derivation, read backwards. One statement per kind, and it is the same one.

    Each branch checks by deriving the key again from what it parsed and comparing, rather
    than by describing the shape a second time. So there is exactly one definition of each
    form, and a second spelling of the same value is refused rather than accepted as an
    alias: ``2026-W07-1`` and ``20260210`` are dates Python parses and neither is a key.
    """
    match kind:
        case BindingKind.ROUTINE | BindingKind.TEMPLATE_ENTRY:
            _require_a_date(kind, key)
        case BindingKind.HABIT:
            _require_an_index(kind, key)
        case BindingKind.TASK:
            _require_exactly(kind, key, TASK_OCCURRENCE_KEY, "one demand per task per week")
        case BindingKind.ANCHOR | BindingKind.ANCHOR_PREP:
            _require_exactly(kind, key, NO_OCCURRENCE, "one of these per anchor")
        case BindingKind.ANCHOR_TRANSIT:
            _require_a_leg(kind, key)
        case _:  # pragma: no cover - unreachable while BindingKind has seven members
            assert_never(kind)


def _require_a_date(kind: BindingKind, key: str) -> None:
    try:
        parsed = date.fromisoformat(key)
    except ValueError as error:
        raise BindingError(_not_a_key(kind, key, "the local date it materializes on")) from error
    if date_occurrence_key(parsed) != key:
        raise BindingError(_not_a_key(kind, key, "the local date it materializes on"))


def _require_an_index(kind: BindingKind, key: str) -> None:
    try:
        index = int(key)
    except ValueError as error:
        raise BindingError(_not_a_key(kind, key, "a zero-padded occurrence index")) from error
    if index < 0 or index_occurrence_key(index) != key:
        raise BindingError(_not_a_key(kind, key, "a zero-padded occurrence index"))


def _require_a_leg(kind: BindingKind, key: str) -> None:
    if key not in {leg.value for leg in TransitLeg}:
        legs = " or ".join(repr(leg.value) for leg in TransitLeg)
        raise BindingError(_not_a_key(kind, key, legs))


def _require_exactly(kind: BindingKind, key: str, expected: str, because: str) -> None:
    if key != expected:
        raise BindingError(_not_a_key(kind, key, f"{expected!r}, because there is {because}"))


def _not_a_key(kind: BindingKind, key: str, expected: str) -> str:
    return (
        f"a {kind.value!r} binding's occurrence key is {expected}, and {key!r} is not: "
        "the key is what separates several blocks of one binding, so a wrong one names "
        "either nothing or another block"
    )


def _require_a_split_only_a_task_can_have(kind: BindingKind, split_index: int | None) -> None:
    """A chunk index belongs to a divided task and to nothing else.

    Only a task is splittable, so a split index on any other kind would name a division
    that cannot exist, and it would change the id of a block that has no chunks.
    """
    if split_index is None:
        return
    if kind is not BindingKind.TASK:
        raise BindingError(
            f"a {kind.value!r} binding carries no split index: only a splittable task is "
            f"divided, so {BindingKind.TASK.value!r} is the one kind with chunks to number"
        )
    if split_index < 0:
        raise BindingError(f"a chunk index counts from zero and this one is {split_index}")
