"""The wire shapes the nine preference routes exchange.

Explicit schemas rather than mapped rows, so a column added to the table does not change the
contract by itself and the generated TypeScript changes only when this file does.

Five properties are stated in the field descriptions rather than only here, because the
descriptions reach the OpenAPI document and therefore the caller.

**``strength`` is ``strong`` or ``soft``.** The enum has two members, so ``hard`` is a stated 422
from the schema rather than a value the service has to refuse. Both are costs the solver trades
off, so neither can leave a block unscheduled, and that is what the description says.

**``maxPerDayMinutes`` is a member of the Area shape and of no other shape.** An override's request
forbids an unknown field, so sending a cap to a habit's or a task's preference is a 422 naming the
field. There is no code path that accepts one, which is what makes an override unable to relax a
hard cap: the cap reaches the solver through the Area's own budget rather than through the
preference in effect, so it is absent from the effective shape too.

**A window is wall time on the quarter hour.** An offset is refused rather than stored and silently
dropped, and so is a second, because every figure the placement arithmetic derives is a count of
minutes. The quarter-hour rule is stated in the domain instead of here, because it is one product
question and one statement of it is what the answer will change.

**``windows`` is required on a request, and an empty list is how a preference states that it names
no time of day.** A defaulted key could not carry that statement: an omitted ``windows`` would
silently opt an override out of its Area's, which is a placement decision nobody made. The key is
therefore required and ``[]`` is explicit. The request shape's description says so and the two
response shapes' do not, because a response always carries the field.

**``effective`` states what is in effect and where it came from.** Its ``source`` is the owner that
declared it, so an override reads as its own and an inherited preference reads as its Area's, and
``statement`` says the same thing in one sentence for a caller that renders rather than compares.
"""

from __future__ import annotations

# `time` is used at runtime by the WallTime alias below, so it carries no type-checking
# suppression the way the identifier import does.
from datetime import time
from typing import Annotated
from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import AfterValidator, ConfigDict, Field

from syncr_api.core.schemas import WireModel
from syncr_domain.preferences import (
    MAX_MAX_PER_DAY_MINUTES,
    MAX_PREFERRED_DURATION_MINUTES,
    MAX_WINDOWS,
    MIN_MAX_PER_DAY_MINUTES,
    MIN_PREFERRED_DURATION_MINUTES,
    LocalTimeWindow,
    Preference,
    PreferenceOwner,
    PreferenceOwnerKind,
    PreferenceStrength,
)
from syncr_domain.snap import SNAP_MINUTES

_BOUND_DESCRIPTION = (
    "Wall time, no date and no zone: '05:30' means 05:30 wherever the user is, resolved against "
    "the zone active on the date the window is read for. Minute resolution, on the quarter hour, "
    "and an offset is refused."
)
_WINDOWS_DESCRIPTION = (
    f"The times of day this owner's work should happen, at most {MAX_WINDOWS} of them, returned "
    "earliest first. A stretch that wraps past midnight is accepted and stored as the two windows "
    "it splits into at midnight, so 23:00 to 01:00 reads back as 23:00 to 00:00 and 00:00 to 01:00 "
    "and counts as two of them. An end of 00:00 therefore means the end of the day, which is the "
    "one bound that may read earlier than the start it belongs to; a stretch whose end equals its "
    "start is refused. They may not overlap: two that do describe one window. "
    "An empty list means this owner names no time of day, and on a habit's or a task's preference "
    "that is a statement rather than an omission, because a preference replaces its Area's windows "
    "wholly: it means this one thing has no preferred time even though the rest of its Area does."
)
# The same field means something more on a request, where an omitted key would otherwise be read as
# the statement above, so the request shape says which and the two response shapes do not.
_WINDOWS_ON_REQUEST = (
    f"{_WINDOWS_DESCRIPTION} Required and not defaulted, so a forgotten key is refused rather than "
    "read as that statement: opting one habit out of its Area's windows is a placement decision "
    "and has to be made on purpose."
)
_STRENGTH_DESCRIPTION = (
    "How much placing the work outside a preferred window costs. Both values are objective costs "
    "rather than constraints, so neither can leave a block unscheduled; 'strong' costs an order "
    "of magnitude more to violate than 'soft'. There is no 'hard': a temporal rule with a "
    "conditional escape is not a hard rule. Required even when no window is declared, in which "
    "case nothing weighs it."
)
_PREFERRED_DURATION_DESCRIPTION = (
    f"How long one session should ideally run, {MIN_PREFERRED_DURATION_MINUTES} to "
    f"{MAX_PREFERRED_DURATION_MINUTES} minutes in whole {SNAP_MINUTES}-minute steps. An IDEAL "
    "only: a task's minimum chunk stays a hard constraint, so a split shorter than this is placed "
    "and charged to the fragmentation cost rather than refused. Null means no ideal length, and "
    "on a habit's or a task's preference null is a statement rather than an omission, because a "
    "preference replaces its Area's ideal duration wholly."
)
_MAX_PER_DAY_DESCRIPTION = (
    f"The most of this Area that may land in one day, {MIN_MAX_PER_DAY_MINUTES} to "
    f"{MAX_MAX_PER_DAY_MINUTES} minutes. A HARD constraint rather than a cost, and an Area's "
    "alone: a habit's or a task's preference has no field for one, so an override can never relax "
    "it. Null means no cap. It reaches the solver through the Area's budget rather than through "
    "the preference in effect, which is why the effective shape does not carry it."
)
_SOURCE_DESCRIPTION = (
    "Which Area, Habit, or Task declared the preference that is in effect. Equal to the owner in "
    "the path when this owner declared its own, and its Area otherwise."
)


def _refuse_a_bound_that_is_not_wall_time(value: time) -> time:
    """Refuse a window bound that names a zone or a second, at the boundary.

    :class:`~syncr_domain.preferences.LocalTimeWindow` refuses the same two shapes, so this is not
    the only line: what it adds is a 422 naming the offending bound rather than the window list. An
    offset would otherwise be stored verbatim inside a JSONB window and read back as a different
    hour on every date the window is resolved against.

    The QUARTER-HOUR rule is deliberately not repeated here. Whether a user-chosen wall time owes
    the grid is one product question, so it is stated once, in the domain, where every writer reads
    it rather than only a request.
    """
    if value.tzinfo is not None:
        raise ValueError(
            "a preferred window is wall time and names no zone, so an offset is refused. Send "
            "'05:30' rather than '05:30+01:00': the zone comes from the date the window is "
            "resolved for."
        )
    if value.second or value.microsecond:
        raise ValueError(
            "a preferred window is minute-resolution, so seconds are refused. Every figure the "
            "placement arithmetic derives is a count of minutes."
        )
    return value


type WallTime = Annotated[time, AfterValidator(_refuse_a_bound_that_is_not_wall_time)]


class TimeWindowRequest(WireModel):
    """One preferred stretch of the day, as the caller states it."""

    model_config = ConfigDict(extra="forbid")

    start: WallTime = Field(description=_BOUND_DESCRIPTION)
    end: WallTime = Field(description=_BOUND_DESCRIPTION)


class TimeWindowResponse(WireModel):
    """One preferred stretch of the day, as it is stored."""

    start: time = Field(description=_BOUND_DESCRIPTION)
    end: time = Field(description=_BOUND_DESCRIPTION)

    @classmethod
    def of(cls, window: LocalTimeWindow) -> TimeWindowResponse:
        return cls(start=window.start, end=window.end)


class PreferenceOwnerResponse(WireModel):
    """One Area, Habit, or Task, named by kind and identifier.

    Two fields rather than three nullable ones, so a client reads which kind it has rather than
    probing three keys, and a shape naming two owners at once is not expressible.
    """

    kind: PreferenceOwnerKind
    id: UUID

    @classmethod
    def of(cls, owner: PreferenceOwner) -> PreferenceOwnerResponse:
        return cls(kind=owner.kind, id=owner.id)


class OverridePreferenceRequest(WireModel):
    """A preference to put on one Habit or Task, whole.

    ``PUT`` rather than ``PATCH``: this replaces its Area's windows and ideal duration wholly, so a
    field left out is null afterwards rather than unchanged, and there is no merge rule to express.

    **There is no ``maxPerDayMinutes`` field here.** A daily cap is a hard constraint and an Area's
    alone, so an unknown field is rejected and sending one is a stated 422. An override that could
    carry a cap would be an override that could relax one.
    """

    model_config = ConfigDict(extra="forbid")

    windows: list[TimeWindowRequest] = Field(
        max_length=MAX_WINDOWS, description=_WINDOWS_ON_REQUEST
    )
    strength: PreferenceStrength = Field(description=_STRENGTH_DESCRIPTION)
    preferred_duration_minutes: int | None = Field(
        default=None,
        strict=True,
        ge=MIN_PREFERRED_DURATION_MINUTES,
        le=MAX_PREFERRED_DURATION_MINUTES,
        description=_PREFERRED_DURATION_DESCRIPTION,
    )


class AreaPreferenceRequest(OverridePreferenceRequest):
    """A preference to put on one Area, whole.

    The override's three fields plus the one an Area alone may declare, so the cap is the only
    difference between the two shapes and it is stated in exactly one of them.
    """

    max_per_day_minutes: int | None = Field(
        default=None,
        strict=True,
        ge=MIN_MAX_PER_DAY_MINUTES,
        le=MAX_MAX_PER_DAY_MINUTES,
        description=_MAX_PER_DAY_DESCRIPTION,
    )


class DeclaredPreferenceResponse(WireModel):
    """The preference set on the owner in the path, exactly as it is stored.

    ``maxPerDayMinutes`` is null on every habit's and every task's, because no request shape can
    set one there and no row may hold one.
    """

    windows: list[TimeWindowResponse] = Field(description=_WINDOWS_DESCRIPTION)
    strength: PreferenceStrength = Field(description=_STRENGTH_DESCRIPTION)
    preferred_duration_minutes: int | None = Field(description=_PREFERRED_DURATION_DESCRIPTION)
    max_per_day_minutes: int | None = Field(description=_MAX_PER_DAY_DESCRIPTION)

    @classmethod
    def of(cls, preference: Preference) -> DeclaredPreferenceResponse:
        return cls(
            windows=[TimeWindowResponse.of(window) for window in preference.windows],
            strength=preference.strength,
            preferred_duration_minutes=preference.preferred_duration_minutes,
            max_per_day_minutes=preference.max_per_day_minutes,
        )


class EffectivePreferenceResponse(WireModel):
    """The one preference the solver reads for this owner, and where it came from.

    It carries no daily cap, and the absence is the contract rather than an omission: a cap travels
    on the Area's budget, so nothing that resolves down an override chain can carry one.
    """

    source: PreferenceOwnerResponse = Field(description=_SOURCE_DESCRIPTION)
    windows: list[TimeWindowResponse] = Field(description=_WINDOWS_DESCRIPTION)
    strength: PreferenceStrength = Field(description=_STRENGTH_DESCRIPTION)
    preferred_duration_minutes: int | None = Field(description=_PREFERRED_DURATION_DESCRIPTION)
    statement: str = Field(
        description=(
            "What is in effect and where it came from, in one sentence, for a caller that renders "
            "rather than compares."
        )
    )

    @classmethod
    def of(cls, preference: Preference, *, owner: PreferenceOwner) -> EffectivePreferenceResponse:
        return cls(
            source=PreferenceOwnerResponse.of(preference.owner),
            windows=[TimeWindowResponse.of(window) for window in preference.windows],
            strength=preference.strength,
            preferred_duration_minutes=preference.preferred_duration_minutes,
            statement=_statement(preference, owner=owner),
        )


class PreferenceResponse(WireModel):
    """What one owner declares, and what is actually in effect for it.

    One shape for all nine routes, so a caller reads the same body from a read, a replacement, and
    a removal, and the answer to "what changed" is the whole state rather than a diff.

    ``declared`` is null when this owner declares none of its own; ``effective`` is null only when
    neither it nor its Area declares one.
    """

    owner: PreferenceOwnerResponse = Field(
        description="The Area, Habit, or Task the path named. Always present: these routes 404 "
        "on an owner that does not exist and never on a preference that is not set."
    )
    declared: DeclaredPreferenceResponse | None = Field(
        description="The preference set on this owner, or null when it declares none of its own."
    )
    effective: EffectivePreferenceResponse | None = Field(
        description="The preference in effect: this owner's own, or its Area's, or null when "
        "neither declares one. Never a merge of the two."
    )


def _statement(preference: Preference, *, owner: PreferenceOwner) -> str:
    """One sentence naming what is in effect and whether this owner declared it."""
    source = (
        f"Set on this {owner.kind.value}"
        if preference.owner == owner
        else "Inherited from its Area"
    )
    windows = " or ".join(str(window) for window in preference.windows)
    times = f"{windows}, {preference.strength.value}" if windows else "no preferred time"
    ideal = (
        f", ideally {preference.preferred_duration_minutes} minutes at a time"
        if preference.preferred_duration_minutes is not None
        else ""
    )
    return f"{source}: {times}{ideal}."
