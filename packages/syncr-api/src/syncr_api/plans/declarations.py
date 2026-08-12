"""What a caller states when it writes a pin, the edit event beside it, or a verdict transition.

Three values rather than long argument lists. The first two are here rather than in either
repository because the pair is written together and has to agree: ``E1`` says an edit event is
written in the same transaction as the pin that caused it, and both carry the same counterfactual,
the same objective delta and the same weight-set version. A field spelled twice across two
signatures is how the two rows would come to disagree about one edit.

Neither of those two carries an id: both are minted by the write, and a pin's row is keyed by the
block rather than by its own identifier, so an id supplied here would be discarded by the first
re-pin.

The third is a whole ``VerdictEvent`` row as its writer states it, and it is the one value in this
module that refuses itself: what a surface may record is narrower than what its columns can hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.plans.errors import VerdictNotRecordable
from syncr_domain.feasibility import Provenance

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.plans.edit_context import EditContext
    from syncr_api.plans.surfaces import VerdictSurface
    from syncr_domain.feasibility import ShortfallKind
    from syncr_domain.identifiers import OperationId
    from syncr_domain.identity import BindingRef, BlockId
    from syncr_domain.intervals import Interval
    from syncr_domain.weeks import IsoWeek


@dataclass(frozen=True, slots=True, kw_only=True)
class PinToHold:
    """One pin, as the row that constrains this week's solve.

    ``interval`` is where the user put the block and ``superseded_placement`` is where the plan of
    record holds it. The two are equal for a pin that states "keep this here", which is what the
    ``p`` toggle and a partial rejection of a proposed move both are.

    There is no objective delta here, and that is the shape of the write rather than an omission:
    one statement holds the row and a second states its cost, inside one transaction.
    """

    iso_week: IsoWeek
    block_id: BlockId
    binding: BindingRef
    interval: Interval
    superseded_placement: Interval
    weight_set_version: int
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class EditToRecord:
    """One edit, as the pairwise preference learning-to-rank consumes.

    ``proposed`` is what the solver chose and ``accepted`` is what the user chose instead, which is
    the comparison. ``context`` is the surrounding state a refit needs, deliberately narrow: roughly
    1.5 KB rather than the 15 KB an embedded week would cost, and every field on it is one a fitter
    reads.
    """

    iso_week: IsoWeek
    binding: BindingRef
    proposed: Interval
    accepted: Interval
    objective_delta: float
    weight_set_version: int
    context: EditContext
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class VerdictToRecord:
    """One verdict transition, as the append-only row that records it.

    ``occurred_at`` is the instant the verdict was computed, taken from the verdict itself rather
    than from a second clock read. That is what makes one instant per tick structural for the
    maintainer: a tick hands one instant to the assembler, the assembler stamps it onto its output,
    the probe carries it onto the verdict, and this row carries it from there, so a tick's
    transitions cannot be evaluated against two instants.

    ``feasible`` is the reading the surface reported, not :attr:`Verdict.feasible`. See
    :func:`syncr_api.plans.verdict_transitions.as_recorded`, which is the one place the two are
    reconciled.

    ``session_mode_active`` has no default, because only the caller knows whether the weekly
    session is open, and a defaulted field is how a surface would acquire that answer without
    stating it.
    """

    iso_week: IsoWeek
    occurred_at: datetime
    provenance: Provenance
    feasible: bool
    shortfall_minutes: int
    shortfall_kinds: tuple[ShortfallKind, ...]
    surface: VerdictSurface
    session_mode_active: bool
    input_version: int
    caused_by_operation_id: OperationId | None = None

    def __post_init__(self) -> None:
        if self.provenance is not self.surface.provenance:
            raise VerdictNotRecordable(
                f"a {self.surface.value} verdict is reached by {self.surface.provenance.value} "
                f"and this one carries {self.provenance.value}: a row whose surface and provenance "
                "disagree records a verdict some other surface computed"
            )
        if (self.provenance is Provenance.SOLVER) != (self.caused_by_operation_id is not None):
            raise VerdictNotRecordable(
                f"a {self.provenance.value} verdict "
                f"{'names no operation' if self.caused_by_operation_id is None else 'names one'}: "
                "a solve's verdict is caused by the operation that ran it, and arithmetic on a "
                "request is caused by nothing a reader could follow"
            )
