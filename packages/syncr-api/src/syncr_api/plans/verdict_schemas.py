"""The verdict on the wire: what a panel renders, and what a shortfall says it cannot satisfy.

Section 09's ``Verdict``, field for field, plus the two readings a client must not compute for
itself.

**``feasible`` and ``capacityIsSufficient`` are two fields because they are two claims.** Capacity
arithmetic proves infeasibility and never feasibility, so a probe verdict finding no gap means it
could not prove the week impossible, which is weaker than the week being possible. A client
rendering ``feasible`` for a probe verdict would assert something nothing computed, so the weaker
reading travels beside it under its own name and the provenance says which to render.

**Every duration is integer minutes**, which is this api's convention throughout, and a shortfall's
own two lists are rendered text: the wording of what cannot be satisfied and of what was honored to
get there is the domain's, so two surfaces cannot word one gap differently.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import TYPE_CHECKING, Self
from uuid import UUID  # noqa: TC003 - as above

from pydantic import Field

from syncr_api.core.schemas import WireModel
from syncr_domain.feasibility import Provenance, ShortfallKind  # noqa: TC001 - as above
from syncr_domain.plan import AdjustmentKind  # noqa: TC001 - as above

if TYPE_CHECKING:
    from syncr_domain.feasibility import Shortfall, Tradeoff, Verdict


class ShortfallResponse(WireModel):
    """One quantified gap: how much, against what, by when, and what was honored to find it."""

    kind: ShortfallKind = Field(description="Which check produced this gap.")
    minutes: int = Field(
        description="The gap itself rather than the demand, so it is what a tradeoff must recover."
    )
    against: list[str] = Field(
        description="What cannot be satisfied, in the user's own words for it: task titles, an "
        "Area's name."
    )
    honoring: list[str] = Field(
        description="The constraints respected while computing the gap, so a reader can see what "
        "the week was measured against rather than only the number."
    )
    deadline: datetime | None = Field(
        description="Present only for a gap measured against a deadline."
    )
    area_id: UUID | None = Field(description="Present only for a gap that belongs to one Area.")

    @classmethod
    def of(cls, shortfall: Shortfall) -> Self:
        return cls(
            kind=shortfall.kind,
            minutes=shortfall.minutes,
            against=list(shortfall.against),
            honoring=list(shortfall.honoring),
            deadline=shortfall.deadline,
            area_id=shortfall.area_id,
        )


class TradeoffResponse(WireModel):
    """One concession the user could approve to close a shortfall, and what it recovers."""

    kind: AdjustmentKind = Field(
        description="The concession this tradeoff becomes if it is approved."
    )
    label: str = Field(
        description="The rendered wording, because it is per kind and per target and names the "
        "nights a reduction would touch."
    )
    target_id: UUID = Field(description="The task, routine, or Area the concession would act on.")
    delta_minutes: int | None = Field(
        description="What approving it would recover, as an UPPER bound rather than an exact "
        "figure. Null where the enumerator could not size the gap it closes."
    )

    @classmethod
    def of(cls, tradeoff: Tradeoff) -> Self:
        return cls(
            kind=tradeoff.kind.value,
            label=tradeoff.label,
            target_id=tradeoff.target_id,
            delta_minutes=tradeoff.delta_minutes,
        )


class VerdictResponse(WireModel):
    """Whether a week can hold its commitments, how that was decided, and by how much it cannot."""

    feasible: bool = Field(
        description="Whether the week is possible. Always false from a capacity probe, which "
        "cannot prove a week works: read capacityIsSufficient instead when provenance is probe."
    )
    capacity_is_sufficient: bool = Field(
        description="Whether this check found no gap. Weaker than feasible: it says the week "
        "could not be proven impossible."
    )
    provenance: Provenance = Field(
        description="probe for capacity arithmetic, which proves infeasibility only, and solver "
        "for a verdict an attempted placement produced."
    )
    computed_at: datetime = Field(
        description="The instant the assembly this verdict was computed from was stamped with, so "
        "two verdicts over one assembly report one instant."
    )
    input_version: int = Field(
        description="The week's input version this verdict was computed against."
    )
    discretionary_minutes: int = Field(
        description="The week's denominator over its whole span, carried so a surface renders the "
        "figure the verdict was computed against rather than re-deriving it."
    )
    shortfalls: list[ShortfallResponse] = Field(
        description="Every quantified gap. Empty when the check found none."
    )
    tradeoffs: list[TradeoffResponse] = Field(
        description="One concession per gap, where the caller enumerated them. Empty from a bare "
        "probe, which reads no identifier and so cannot name what a concession would act on."
    )

    @classmethod
    def of(cls, verdict: Verdict) -> Self:
        """The wire shape of one verdict."""
        return cls(
            feasible=verdict.feasible,
            capacity_is_sufficient=verdict.capacity_is_sufficient,
            provenance=verdict.provenance,
            computed_at=verdict.computed_at,
            input_version=verdict.input_version,
            discretionary_minutes=verdict.discretionary_minutes,
            shortfalls=[ShortfallResponse.of(one) for one in verdict.shortfalls],
            tradeoffs=[TradeoffResponse.of(one) for one in verdict.tradeoffs],
        )
