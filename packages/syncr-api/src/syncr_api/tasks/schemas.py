"""The wire shapes the backlog routes exchange.

Explicit schemas rather than mapped rows, so a column added to the table does not change the
contract by itself and the generated TypeScript changes only when this file does.

Three properties of these shapes are stated in the field descriptions rather than only here,
because the descriptions reach the OpenAPI document and therefore the caller.

**There is no preferred-time field anywhere in these shapes.** Preferred times are a
``Preference``, whose owner is an Area, a Habit, or a Task, so a task inherits its Area's windows
unless it overrides them. Both request shapes forbid an unknown field, so sending
``preferredTimes`` is a stated 422 rather than a value quietly dropped.

**T1 is not restated here.** ``minChunkMinutes <= estimateMinutes`` is arithmetic over two of the
task's own numbers and it lives in ``syncr_domain.tasks``, which is what produces the 422 and its
stated reason. There is deliberately no validator in this file comparing the two: a second
statement of the rule would be one that could disagree, and a partial update needs the comparison
made against the MERGED pair rather than against the fields one request happened to send.

**A capture needs a title and an Area.** Everything else has a default, and each default is
stated in its own description, so the two-field capture is visible in the document rather than
only in this module.

**Every minute field is strict.** Pydantic's lax mode reads `true` as 1 and `"30"` as 30, so a
client sending a boolean where a duration belongs would store a one-minute task rather than be told
it sent the wrong kind of value. The JSON schema type is `integer` either way, so this narrows what
is accepted without changing the contract.
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import ConfigDict, Field, field_validator

from syncr_api.core.schemas import WireInstant, WireModel, WireText
from syncr_api.tasks.config import (
    ESTIMATE_MINUTES_MAX,
    ESTIMATE_MINUTES_MIN,
    MIN_CHUNK_MINUTES_MAX,
    MIN_CHUNK_MINUTES_MIN,
    TITLE_MAX_LENGTH,
)
from syncr_domain.tasks import (
    DEFAULT_ESTIMATE_MINUTES,
    DEFAULT_MIN_CHUNK_MINUTES,
    DEFAULT_PRIORITY,
    DEFAULT_SPLITTABLE,
    Priority,
    TaskStatus,
)

_TITLE_DESCRIPTION = "What the work is, in the user's own words. Required on capture."
_AREA_DESCRIPTION = (
    "The one Area this task's time counts toward. Required on capture, and declared once: the "
    "hours already recorded against a task were attributed to this Area, so moving it would "
    "rewrite reported history."
)
_PROJECT_DESCRIPTION = (
    "The time-boxed push this task belongs to, or null for none. Its Area has to be this task's "
    "Area, because a project sits in exactly one Area and an hour is attributable to one."
)
_ESTIMATE_DESCRIPTION = (
    f"Total work in minutes, {ESTIMATE_MINUTES_MIN} to {ESTIMATE_MINUTES_MAX}. Defaults to "
    f"{DEFAULT_ESTIMATE_MINUTES}, which is two grid steps: the smallest estimate the default "
    "minimum chunk can divide. Never reduced by recording time against the task; remaining work "
    "is the difference."
)
_DEADLINE_DESCRIPTION = (
    "When the work is due, or null for no deadline, which is the default. A deadline is read by "
    "the feasibility probe rather than enforced here: a task with no capacity before it is "
    "reported, never refused."
)
_PRIORITY_DESCRIPTION = (
    f"How much the objective prefers this task over another in the same Area. Defaults to "
    f"'{DEFAULT_PRIORITY.value}'."
)
_MIN_CHUNK_DESCRIPTION = (
    f"The smallest placement a splittable task may be divided into, {MIN_CHUNK_MINUTES_MIN} to "
    f"{MIN_CHUNK_MINUTES_MAX} minutes. Defaults to {DEFAULT_MIN_CHUNK_MINUTES}, one grid step, "
    "clamped down to the estimate when the estimate is smaller. A value above the estimate is "
    "refused with a stated reason, because no placement could satisfy both. Stored but unread on "
    "an atomic task, whose only placement is the whole estimate: it is kept rather than forced to "
    "the estimate so that making the task splittable again restores the minimum the user chose."
)
_SPLITTABLE_DESCRIPTION = (
    f"Whether the solver may divide this task across several placements. Defaults to "
    f"{str(DEFAULT_SPLITTABLE).lower()}; false means atomic, so it is placed as one block of the "
    "whole estimate or not placed."
)

_NOT_NULLABLE_MESSAGE = (
    "this field cannot be cleared, so null is refused rather than read as no change. Leave it "
    "out to keep the stored value."
)


class TaskResponse(WireModel):
    """One task, with the two figures the backlog renders that no column holds."""

    id: UUID
    area_id: UUID = Field(description=_AREA_DESCRIPTION)
    project_id: UUID | None = Field(description=_PROJECT_DESCRIPTION)
    title: str = Field(description=_TITLE_DESCRIPTION)
    estimate_minutes: int = Field(description=_ESTIMATE_DESCRIPTION)
    recorded_minutes: int = Field(
        description="Minutes confirmed against this task. Accumulated from outcomes, left intact "
        "by completing, so the time spent survives in reports."
    )
    remaining_minutes: int = Field(
        description="Work left: the estimate less what was recorded, never negative. Recording "
        "more than was estimated reports zero rather than a negative figure."
    )
    deadline: WireInstant | None = Field(description=_DEADLINE_DESCRIPTION)
    priority: Priority = Field(description=_PRIORITY_DESCRIPTION)
    min_chunk_minutes: int = Field(description=_MIN_CHUNK_DESCRIPTION)
    splittable: bool = Field(description=_SPLITTABLE_DESCRIPTION)
    status: TaskStatus
    completed_at: WireInstant | None = Field(
        description="When this task was completed, null otherwise. A dropped task has no "
        "instant: nothing reports one, and a completion is what reports read."
    )
    eligible_for_solving: bool = Field(
        description="Whether the next solve may place this task: open, with work left. A "
        "captured task is eligible immediately."
    )


class BacklogTaskResponse(TaskResponse):
    """One task as the BACKLOG lists it: everything above, plus whether it is at risk.

    A shape of its own rather than a field on ``TaskResponse``, because at-risk is a fact about the
    week's verdict rather than about the row. The six routes that answer about one task would have
    to assemble a week to state it truthfully, and a mutation that computed a verdict would owe a
    recorded transition; answering false there instead would be a claim none of them checked. So the
    marking is on the read that has the figure beside it, and nowhere else.
    """

    at_risk: bool = Field(
        description="Whether the current week's verdict reports a deadlineCapacity shortfall "
        "naming this task. The server's determination, not a comparison a client makes: the same "
        "shortfall the verdict panel renders, so a task cannot be at risk on one screen and fine "
        "on another. False for a task with no deadline and for a week with no plan."
    )


class BacklogHeader(WireModel):
    """The two counts the backlog's header band states."""

    open_count: int = Field(
        description="How many tasks are open. Unaffected by the status and atRisk filters, "
        "because a count of open tasks that reported zero while the table showed completed ones "
        "would not be one. Narrowed by the area filter, which narrows the whole screen."
    )
    at_risk_count: int = Field(
        description="How many open tasks the current week's verdict reports a deadline shortfall "
        "for. Over the same population as openCount, so the figure and the marked rows are one "
        "answer, and unaffected by the status and atRisk filters for the reason openCount is: "
        "narrowing the table to the marked rows does not change how many of them there are. "
        "Recomputed on every read rather than on a timer, and nothing pushes it: the "
        "event stream carries no verdict member, because only a conflict notifies."
    )


class TasksResponse(WireModel):
    """The backlog: its header counts, and the tasks the filters selected.

    A wrapper rather than a bare array, so the header counts travel with the rows they describe
    and a caller cannot render a count derived from a filtered page. Not paginated: a personal
    backlog is bounded by what one person can hold, and `13-http-api.md` reserves cursors for the
    collections that grow without a ceiling.
    """

    header: BacklogHeader
    tasks: list[BacklogTaskResponse]


class TaskCreateRequest(WireModel):
    """A task to capture. A title and an Area are required; everything else has a default."""

    model_config = ConfigDict(extra="forbid")

    area_id: UUID = Field(description=_AREA_DESCRIPTION)
    title: WireText = Field(
        min_length=1, max_length=TITLE_MAX_LENGTH, description=_TITLE_DESCRIPTION
    )
    project_id: UUID | None = Field(default=None, description=_PROJECT_DESCRIPTION)
    estimate_minutes: int = Field(
        default=DEFAULT_ESTIMATE_MINUTES,
        ge=ESTIMATE_MINUTES_MIN,
        le=ESTIMATE_MINUTES_MAX,
        strict=True,
        description=_ESTIMATE_DESCRIPTION,
    )
    deadline: WireInstant | None = Field(default=None, description=_DEADLINE_DESCRIPTION)
    priority: Priority = Field(default=DEFAULT_PRIORITY, description=_PRIORITY_DESCRIPTION)
    # Null rather than a literal default, because the default is DERIVED from the estimate: one
    # grid step, clamped down to a smaller stated estimate. Filling it here would make the
    # document state a value that is wrong for a small estimate, and it would put the derivation
    # in a request schema rather than in the domain that owns the rule it exists to satisfy.
    min_chunk_minutes: int | None = Field(
        default=None,
        ge=MIN_CHUNK_MINUTES_MIN,
        le=MIN_CHUNK_MINUTES_MAX,
        strict=True,
        description=_MIN_CHUNK_DESCRIPTION,
    )
    splittable: bool = Field(default=DEFAULT_SPLITTABLE, description=_SPLITTABLE_DESCRIPTION)


class TaskPatchRequest(WireModel):
    """A partial update. An omitted field is left alone; an explicit null clears one.

    Only ``projectId`` and ``deadline`` are nullable, and clearing either is a real intention: a
    task can leave a project and a deadline can be removed. The rest refuse null.

    ``status``, ``recordedMinutes``, and ``areaId`` are not members of this shape and an unknown
    field is rejected, so sending one is a stated 422. A task ends through ``POST
    .../complete`` or ``DELETE``, each of which records what it owes; recorded minutes come from
    confirmed outcomes; and an Area is declared once.
    """

    model_config = ConfigDict(extra="forbid")

    title: WireText | None = Field(
        default=None, min_length=1, max_length=TITLE_MAX_LENGTH, description=_TITLE_DESCRIPTION
    )
    project_id: UUID | None = Field(default=None, description=_PROJECT_DESCRIPTION)
    estimate_minutes: int | None = Field(
        default=None,
        ge=ESTIMATE_MINUTES_MIN,
        le=ESTIMATE_MINUTES_MAX,
        strict=True,
        description=_ESTIMATE_DESCRIPTION,
    )
    deadline: WireInstant | None = Field(default=None, description=_DEADLINE_DESCRIPTION)
    priority: Priority | None = Field(default=None, description=_PRIORITY_DESCRIPTION)
    min_chunk_minutes: int | None = Field(
        default=None,
        ge=MIN_CHUNK_MINUTES_MIN,
        le=MIN_CHUNK_MINUTES_MAX,
        strict=True,
        description=_MIN_CHUNK_DESCRIPTION,
    )
    splittable: bool | None = Field(default=None, description=_SPLITTABLE_DESCRIPTION)

    @field_validator("title", "estimate_minutes", "priority", "min_chunk_minutes", "splittable")
    @classmethod
    def _refuse_an_explicit_null(cls, value: object) -> object:
        """Refuse ``null`` on the five fields that have nothing to clear.

        A validator runs only for a field the request actually named, so an omitted field is
        untouched by this and an explicit null is a stated 422. Without it, both would arrive as
        ``None`` and the two intentions would be indistinguishable.
        """
        if value is None:
            raise ValueError(_NOT_NULLABLE_MESSAGE)
        return value
