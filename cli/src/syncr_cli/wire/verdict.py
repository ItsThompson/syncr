"""The verdict a week carries, as the CLI reads it and prints its provenance.

**This reader models less than the contract carries, deliberately.** The api answers
``verdict: null`` exactly when the week holds no plan, and its ``VerdictResponse`` carries more
members than the headline is composed from, so this reader requires only ``feasible`` and
``provenance`` and treats the shortfalls and the tradeoffs as absent-is-empty. A smaller claim
is a claim a contract change is less likely to falsify, and the ``--json`` output carries the
api's own payload verbatim whatever this reader models.

The vocabulary and the duration wording are the domain's, imported rather than restated:
``ShortfallKind`` crosses the api boundary and renders on three surfaces, and
``hours_and_minutes`` is the one rendering of a duration the whole product prints, so a second
spelling of either here is how two surfaces come to disagree about one figure.

**The provenance is printed, always.** A probe can prove a week impossible and cannot prove one
possible, so a reading that did not attempt a placement says ``[capacity check]`` and one that
did says ``[after solving]``. The product never asserts a certainty it does not have.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from syncr_cli.errors import MalformedResponse
from syncr_cli.wire.reading import (
    JsonMapping,
    boolean,
    integer,
    mappings,
    optional_instant,
    text,
)
from syncr_domain.feasibility.verdict import Provenance, hours_and_minutes

if TYPE_CHECKING:
    from datetime import datetime

# What the ledger prints after the headline, per provenance. The words are fixed rather than chosen
# here: stdout is a contract with the agent reading it, and the ledger's suite asserts both.
PROVENANCE_TAGS: dict[Provenance, str] = {
    Provenance.PROBE: "[capacity check]",
    Provenance.SOLVER: "[after solving]",
}

INFEASIBLE_HEADLINE = "This week cannot hold its commitments"
FEASIBLE_HEADLINE = "This week holds its commitments"
# Never "this week works". Capacity arithmetic finding nothing means it could not prove the week
# impossible, which is the weaker statement.
SUFFICIENT_HEADLINE = "Capacity is sufficient"

NOTHING_IS_CHOSEN = "Nothing is chosen for you."


@dataclass(frozen=True, slots=True)
class Shortfall:
    """One quantified gap: how much, against what, by when, and what was honored to get there."""

    minutes: int
    against: tuple[str, ...]
    honoring: tuple[str, ...]
    deadline: datetime | None

    @classmethod
    def read(cls, payload: JsonMapping, path: str) -> Self:
        return cls(
            minutes=_gap_minutes(payload, path),
            against=_names(payload, "against", path),
            honoring=_names(payload, "honoring", path),
            deadline=optional_instant(payload, "deadline", path),
        )

    def statement(self, *, deadline: str | None) -> str:
        """This gap as one sentence, with the deadline already rendered by the caller.

        The deadline arrives rendered because naming ``Fri 09:00`` needs the zone the user is
        in on that date, and the week's zone map is what holds it.
        """
        sentence = f"{hours_and_minutes(self.minutes)} short on {_joined(self.against)}"
        if deadline is not None:
            sentence = f"{sentence} before {deadline}"
        if self.honoring:
            sentence = f"{sentence}, after honoring {_joined(self.honoring)}"
        return f"{sentence}."


@dataclass(frozen=True, slots=True)
class Verdict:
    """Whether a week can hold its commitments, and how that was decided.

    ``payload`` is the api's own object, kept so ``--json`` emits what the api sent rather than
    a re-spelling of it that could drop a member this build does not read.
    """

    feasible: bool
    provenance: Provenance
    shortfalls: tuple[Shortfall, ...]
    tradeoff_count: int
    payload: JsonMapping

    @classmethod
    def read(cls, payload: JsonMapping, path: str) -> Self:
        return cls(
            feasible=boolean(payload, "feasible", path),
            provenance=_provenance(payload, path),
            shortfalls=tuple(
                Shortfall.read(entry, f"{path}.shortfalls[{index}]")
                for index, entry in enumerate(_optional_mappings(payload, "shortfalls", path))
            ),
            tradeoff_count=len(_optional_mappings(payload, "tradeoffs", path)),
            payload=payload,
        )

    @property
    def capacity_is_sufficient(self) -> bool:
        """Whether this check found no gap. **Not** a claim that the week works."""
        return not self.shortfalls

    @property
    def is_infeasible(self) -> bool:
        """Whether this verdict is the one that exits 8.

        A gap is infeasibility whoever found it. A solver reporting ``feasible: false`` with no
        gap is infeasibility too: it attempted a placement and failed, and the exit code must
        not depend on whether the failure came with an explanation.
        """
        if self.shortfalls:
            return True
        return self.provenance is Provenance.SOLVER and not self.feasible

    @property
    def headline(self) -> str:
        """The one line the ledger prints, without its provenance tag."""
        if self.is_infeasible:
            return INFEASIBLE_HEADLINE
        if self.provenance is Provenance.PROBE:
            return SUFFICIENT_HEADLINE
        return FEASIBLE_HEADLINE

    @property
    def tag(self) -> str:
        """Where this verdict came from, in the words the ledger prints."""
        return PROVENANCE_TAGS[self.provenance]


def _gap_minutes(payload: JsonMapping, path: str) -> int:
    """A shortfall's gap, refused here rather than by the renderer that would print it.

    The domain refuses a gap of none or less at construction, and the duration renderer refuses a
    negative figure, so a payload carrying one would fault inside the human renderer while the JSON
    renderer answered normally: the one place the two renderings could disagree about whether a
    response is usable. Refused where the payload is read, like every other unusable value.
    """
    minutes = integer(payload, "minutes", path)
    if minutes <= 0:
        raise MalformedResponse(
            f"{path}.minutes is {minutes}, and a shortfall is a gap of something: enough capacity "
            "reports nothing rather than a gap of none. Nothing was changed."
        )
    return minutes


def _provenance(payload: JsonMapping, path: str) -> Provenance:
    raw = text(payload, "provenance", path)
    try:
        return Provenance(raw)
    except ValueError as error:
        named = ", ".join(sorted(member.value for member in Provenance))
        raise MalformedResponse(
            f"{path}.provenance is {raw!r}, and a verdict is produced by one of: {named}. This "
            "CLI will not print a provenance it cannot name."
        ) from error


def _names(payload: JsonMapping, name: str, path: str) -> tuple[str, ...]:
    raw = payload.get(name)
    if not isinstance(raw, list):
        return ()
    return tuple(entry for entry in raw if isinstance(entry, str) and entry.strip())


def _optional_mappings(payload: JsonMapping, name: str, path: str) -> list[JsonMapping]:
    if payload.get(name) is None:
        return []
    return mappings(payload, name, path)


def _joined(names: tuple[str, ...]) -> str:
    """A list of names as prose: ``a``, ``a and b``, ``a, b and c``."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"
