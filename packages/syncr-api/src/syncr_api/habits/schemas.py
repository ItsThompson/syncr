"""The wire shapes the habit routes exchange.

Explicit schemas rather than mapped rows, so a column added to the table does not change the
contract by itself and the generated TypeScript changes only when this file does.

Three properties of these shapes are stated in the field descriptions as well as here, because
the descriptions reach the OpenAPI document and therefore the caller.

**The cursor is read-only, on every response, with its provenance.** No request shape has a
cursor field and both mutating requests forbid an unknown field, so ``PATCH`` carrying one is a
stated 422 rather than a value quietly dropped. A habit that does not rotate renders ``null``,
because a fixed habit displays no cursor at all rather than displaying zero.

**There is no preferred time anywhere in these shapes.** When a habit's work should happen is a
``Preference``, whose owner may be this habit, and it is authored through the habit's own
preference route. A field here would be a second home for the value, and the solver would have
to decide which one wins.

**A duration is a floor and a ceiling.** Omitting the ceiling on a create means it equals the
floor, which is what a fixed duration is: this span or nothing. Both bounds reach the wire, so a
client compares them rather than reading a kind, and no request carries a discriminator that
could disagree with the numbers beside it.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import ConfigDict, Field, field_validator

from syncr_api.core.schemas import WireInstant, WireModel, WireText
from syncr_api.habits.config import HABIT_TITLE_MAX_LENGTH
from syncr_domain.habits import (
    DEFAULT_DEBT_CAP_PERIODS,
    MAX_APPROX_DAYS,
    MAX_DEBT_CAP_PERIODS,
    MAX_DURATION_MINUTES,
    MAX_TIMES_PER_WEEK,
    MAX_VARIANTS,
    MIN_APPROX_DAYS,
    MIN_DEBT_CAP_PERIODS,
    MIN_DURATION_MINUTES,
    VARIANT_MAX_LENGTH,
    BindingSource,
    CadenceKind,
    MissPolicy,
)

_NOT_NULLABLE_MESSAGE = (
    "this field cannot be cleared, so null is refused rather than read as no change. "
    "Leave it out to keep the stored value."
)

_VARIANTS_DESCRIPTION = (
    "The ordered content a rotation cycles through. Non-empty exactly when bindingSource is "
    f"{BindingSource.ROTATION.value!r}, and empty for every other source: a "
    f"{BindingSource.FIXED.value!r} habit repeats one content and a "
    f"{BindingSource.QUEUE.value!r} habit draws it from the backlog."
)
_MIN_DURATION_DESCRIPTION = (
    "The floor of one occurrence, in minutes. It is also the whole duration when there is no "
    f"ceiling above it. A multiple of 15, between {MIN_DURATION_MINUTES} and "
    f"{MAX_DURATION_MINUTES}, because a block's start and end both land on the quarter hour."
)
_MAX_DURATION_DESCRIPTION = (
    "The ceiling of one occurrence, in minutes. Equal to the floor means the duration is fixed: "
    "this span or nothing."
)
_DEBT_CAP_DESCRIPTION = (
    "The ceiling on outstanding debt, in cadence periods. One period is a week for a "
    "count-per-week habit, a day for a daily one, and the stated interval for an approximate "
    "one, so the cap is that many periods' worth of occurrences. A miss arriving at the cap is "
    "forgiven rather than added, and raises the habit in the weekly session."
)


class CadenceRequest(WireModel):
    """A cadence to declare: a kind, and the one number that kind uses.

    A single shape with two optional numbers rather than three shapes, because a discriminated
    union would generate three TypeScript types for one concept. The number the kind does not use
    is refused, so a body carrying both cannot resolve to whichever the kind happens to name.
    """

    model_config = ConfigDict(extra="forbid")

    kind: CadenceKind = Field(
        description="times_per_week takes a count, every_approx_days takes an interval in days, "
        "and daily takes neither. Cadence lives on a habit and never on a template."
    )
    times_per_week: int | None = Field(
        default=None,
        ge=1,
        le=MAX_TIMES_PER_WEEK,
        description="How many occurrences a week holds. Required for times_per_week, refused "
        "for the other two.",
    )
    approx_days: int | None = Field(
        default=None,
        ge=MIN_APPROX_DAYS,
        le=MAX_APPROX_DAYS,
        description="Roughly how many days apart occurrences fall. Required for "
        "every_approx_days, refused for the other two. An interval of one day is daily, which "
        "is the one spelling of it.",
    )


class CadenceResponse(WireModel):
    """The cadence a habit holds, in the same shape a request declares one in."""

    kind: CadenceKind
    times_per_week: int | None
    approx_days: int | None


class CursorResponse(WireModel):
    """Where a rotation habit's cursor sits, and what it rests on. Read-only, always.

    Derived from the append-only outcome log rather than stored, so there is no route that sets
    it and no field on any request that could. A wrong cursor means a wrong confirmation: the
    user fixes the day on Today and this re-derives with no further action.
    """

    index: int = Field(description="The index into variants this habit's next occurrence binds.")
    variant: str = Field(description="The content at that index.")
    confirmed_completions: int = Field(
        description="How many confirmed completions the outcome log holds for this habit. The "
        "cursor is this count modulo the variant count, which is why a skip does not advance it."
    )
    previous_variant: str | None = Field(
        description="The variant whose confirmed completion put the cursor here, or null before "
        "the first one."
    )
    advanced_at: WireInstant | None = Field(
        description="When the most recent confirmed completion was confirmed, or null."
    )
    statement: str = Field(
        description="Why the cursor is where it is, in the words an interface renders beside it."
    )


class DebtResponse(WireModel):
    """What this habit's misses amount to under its policy. Derived, so also read-only."""

    outstanding: int = Field(
        description="Confirmed skips of this habit's occurrences, clamped to the cap, which the "
        "week assembler adds to a week as made-up occurrences. It falls only when the log stops "
        "recording an occurrence as missed, which is what correcting the day on Today does: "
        "performing a make-up does not currently reduce it. Always zero for forgive and for "
        "escalate, because only debt accumulates."
    )
    cap: int = Field(
        description="The ceiling: debtCapPeriods times the occurrences one cadence period holds."
    )
    misses: int = Field(description="Confirmed skips the outcome log holds for this habit.")
    forgiven_at_cap: int = Field(
        description="Misses that arrived while debt was already at the cap. Each was forgiven "
        "rather than added."
    )
    raised_in_weekly_session: bool = Field(
        description="Whether this habit is raised in the next weekly session, through the same "
        "field chronic skips use. True when a miss was forgiven at the cap, and true for an "
        "escalate habit with any miss."
    )
    statement: str = Field(description="The figure in the words an interface renders.")


class HabitResponse(WireModel):
    """One habit, with both derivations rendered beside it and neither settable."""

    id: UUID
    area_id: UUID = Field(
        description="The one Area this habit's occurrences count toward. Declared once: moving "
        "it would re-attribute hours that have already been reported."
    )
    title: str
    cadence: CadenceResponse
    min_duration_minutes: int = Field(description=_MIN_DURATION_DESCRIPTION)
    max_duration_minutes: int = Field(description=_MAX_DURATION_DESCRIPTION)
    miss_policy: MissPolicy
    binding_source: BindingSource
    variants: list[str] = Field(description=_VARIANTS_DESCRIPTION)
    debt_cap_periods: int = Field(description=_DEBT_CAP_DESCRIPTION)
    cursor: CursorResponse | None = Field(
        description="Read-only, with its provenance. Null for a habit that does not rotate: a "
        "fixed habit displays no cursor at all. There is no route that sets one."
    )
    debt: DebtResponse = Field(description="Derived from the outcome log. Read-only.")


class HabitsResponse(WireModel):
    """Every habit a tenant has declared, in the order they were declared.

    A wrapper rather than a bare array. The collection is bounded by how many recurring
    intentions a person holds, so it is not paginated, and an object leaves room beside it.
    """

    habits: list[HabitResponse]


type _Title = Annotated[WireText, Field(min_length=1, max_length=HABIT_TITLE_MAX_LENGTH)]
type _Variants = Annotated[
    list[Annotated[WireText, Field(min_length=1, max_length=VARIANT_MAX_LENGTH)]],
    Field(max_length=MAX_VARIANTS),
]
type _Duration = Annotated[int, Field(ge=MIN_DURATION_MINUTES, le=MAX_DURATION_MINUTES)]
type _DebtCap = Annotated[int, Field(ge=MIN_DEBT_CAP_PERIODS, le=MAX_DEBT_CAP_PERIODS)]


class HabitCreateRequest(WireModel):
    """A habit to declare, inside an Area that already exists.

    No cursor field and no preferred-time field, and an unknown field is rejected, so a body
    carrying either is a stated 422 rather than a value quietly dropped.
    """

    model_config = ConfigDict(extra="forbid")

    area_id: UUID
    title: _Title
    cadence: CadenceRequest
    min_duration_minutes: _Duration = Field(description=_MIN_DURATION_DESCRIPTION)
    max_duration_minutes: _Duration | None = Field(
        default=None,
        description=f"{_MAX_DURATION_DESCRIPTION} Omit it for a fixed duration, which sets it "
        "equal to the floor.",
    )
    miss_policy: MissPolicy = MissPolicy.FORGIVE
    binding_source: BindingSource = BindingSource.FIXED
    variants: _Variants = Field(default_factory=list, description=_VARIANTS_DESCRIPTION)
    debt_cap_periods: _DebtCap = Field(
        default=DEFAULT_DEBT_CAP_PERIODS, description=_DEBT_CAP_DESCRIPTION
    )


class HabitPatchRequest(WireModel):
    """A partial update. An omitted field is left alone, and an explicit null is refused.

    Nothing on a habit is nullable, so there is no third case to express: ``null`` on any field
    here is a stated 422 rather than a value read as "no change".

    ``areaId`` is not a member of this shape, and neither is ``cursor`` nor any preferred time.
    An unknown field is rejected, so sending one is a stated 422.
    """

    model_config = ConfigDict(extra="forbid")

    title: _Title | None = None
    cadence: CadenceRequest | None = None
    min_duration_minutes: _Duration | None = Field(
        default=None, description=_MIN_DURATION_DESCRIPTION
    )
    max_duration_minutes: _Duration | None = Field(
        default=None, description=_MAX_DURATION_DESCRIPTION
    )
    miss_policy: MissPolicy | None = None
    binding_source: BindingSource | None = None
    variants: _Variants | None = Field(default=None, description=_VARIANTS_DESCRIPTION)
    debt_cap_periods: _DebtCap | None = Field(default=None, description=_DEBT_CAP_DESCRIPTION)

    @field_validator(
        "title",
        "cadence",
        "min_duration_minutes",
        "max_duration_minutes",
        "miss_policy",
        "binding_source",
        "variants",
        "debt_cap_periods",
    )
    @classmethod
    def _refuse_an_explicit_null(cls, value: object) -> object:
        """Refuse ``null`` on every field, because none of them has anything to clear.

        A validator runs only for a field the request actually named, so an omitted field is
        untouched by this and an explicit null is a stated 422. Without it, both would arrive as
        ``None`` and the two intentions would be indistinguishable.

        A rotation is switched off by naming the new source and an empty ``variants`` list, not
        by clearing the list: clearing it alone would leave a rotation with nothing to index,
        which X3 refuses.
        """
        if value is None:
            raise ValueError(_NOT_NULLABLE_MESSAGE)
        return value


class HabitRemoved(WireModel):
    """What a removal answers with, so a retried removal replays rather than 404ing.

    The route responds ``204`` and this body never reaches the wire. It exists because the
    idempotency guard stores and replays a response MODEL, and a removal has no other shape to
    store: without it, a retry with the same key would find the habit already gone.
    """

    removed: Literal[True] = True
