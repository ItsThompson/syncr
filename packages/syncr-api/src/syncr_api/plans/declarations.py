"""What a caller states when it writes a pin and the edit event beside it.

Two values rather than long argument lists, and they are here rather than in either repository
because the pair is written together and has to agree: ``E1`` says an edit event is written in the
same transaction as the pin that caused it, and both carry the same counterfactual, the same
objective delta and the same weight-set version. A field spelled twice across two signatures is how
the two rows would come to disagree about one edit.

Neither carries an id: both are minted by the write, and a pin's row is keyed by the block rather
than by its own identifier, so an id supplied here would be discarded by the first re-pin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.plans.edit_context import EditContext
    from syncr_domain.identity import BindingRef, BlockId
    from syncr_domain.intervals import Interval
    from syncr_domain.weeks import IsoWeek


@dataclass(frozen=True, slots=True, kw_only=True)
class PinToHold:
    """One pin, as the row that constrains this week's solve.

    ``interval`` is where the user put the block and ``superseded_placement`` is where the plan of
    record holds it. The two are equal for a pin that states "keep this here", which is what the
    ``p`` toggle and a partial rejection of a proposed move both are.

    There is no objective delta here, and that is the ordering rather than an omission: the price is
    derived from an assembly this pin changes, so the row is written first and priced second, inside
    one transaction.
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
