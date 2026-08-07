"""The wire shapes the three learning routes answer with.

Camel-cased on the wire, as every other schema in this api is, so the generated TypeScript reads the
way a frontend expects and the Python reads the way the rest of this package does.
"""

from __future__ import annotations

# Runtime, not type-only: pydantic resolves a field annotation when the model is built.
from datetime import datetime
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_api.learned.maturity import ParameterMaturityReading
    from syncr_api.learned.views import ActivatedWeightSet, LearnedReading, WeightSetSummary


class LearnedSchema(BaseModel):
    """The camel-casing every shape here inherits."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ParameterResponse(LearnedSchema):
    """One row of the Learned screen."""

    parameter: str = Field(description="The parameter, with its key where it has one.")
    samples: int = Field(description="Observations behind it.")
    threshold: int = Field(description="How many it needs before it is applied. An ESTIMATE.")
    state: str = Field(description="`collecting` or `ready`.")
    value: float | None = Field(description="The fitted figure, or null while collecting.")
    shrinkage_weight: float = Field(
        description="How much of the value is still the prior, from 0 to 1."
    )
    plain_language: str = Field(description="What this row means, in the user's own terms.")

    @classmethod
    def of(cls, row: ParameterMaturityReading) -> Self:
        return cls(
            parameter=row.parameter,
            samples=row.samples,
            threshold=row.threshold,
            state=row.state,
            value=row.value,
            shrinkage_weight=row.shrinkage_weight,
            plain_language=row.plain_language,
        )


class LearnedResponse(LearnedSchema):
    """Everything the Learned screen renders."""

    version: int
    origin: str
    fitted_at: datetime | None
    parameters: list[ParameterResponse]
    ready: int
    collecting: int
    thresholds_are_estimates: str
    unlocks_count_confirmed_volume: str
    collecting_is_normal: str

    @classmethod
    def of(cls, reading: LearnedReading) -> Self:
        return cls(
            version=reading.version,
            origin=reading.origin,
            fitted_at=reading.fitted_at,
            parameters=[ParameterResponse.of(one) for one in reading.rows],
            ready=reading.ready,
            collecting=reading.collecting,
            thresholds_are_estimates=reading.thresholds_are_estimates,
            unlocks_count_confirmed_volume=reading.unlocks_count_confirmed_volume,
            collecting_is_normal=reading.collecting_is_normal,
        )


class WeightSetResponse(LearnedSchema):
    """One version, as the list renders it."""

    version: int
    origin: str
    active: bool
    fitted_at: datetime | None
    created_at: datetime
    ready: int
    collecting: int

    @classmethod
    def of(cls, summary: WeightSetSummary) -> Self:
        return cls(
            version=summary.version,
            origin=summary.origin,
            active=summary.active,
            fitted_at=summary.fitted_at,
            created_at=summary.created_at,
            ready=summary.ready,
            collecting=summary.collecting,
        )


class WeightSetsResponse(LearnedSchema):
    """Every version this account holds, newest first."""

    versions: list[WeightSetResponse]

    @classmethod
    def of(cls, summaries: Sequence[WeightSetSummary]) -> Self:
        return cls(versions=[WeightSetResponse.of(one) for one in summaries])


class ActivatedResponse(LearnedSchema):
    """The version now in force, and the future weeks the activation re-solved."""

    version: int
    resolved_weeks: list[str] = Field(
        description="The FUTURE weeks re-solved. A past week's approved revision is immutable."
    )

    @classmethod
    def of(cls, activated: ActivatedWeightSet) -> Self:
        return cls(version=activated.version, resolved_weeks=list(activated.resolved_weeks))
