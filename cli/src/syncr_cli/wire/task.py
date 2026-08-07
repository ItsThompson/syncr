"""The backlog: the tasks a filter selected, and the two counts the server computed for them.

Only the members a rendering prints are read. A response carries more than that, and reading a
member this package does not render would be a claim about the contract nothing here needs to make.

**The at-risk figure is the server's determination, never a comparison made here.** A task is at
risk when the feasibility probe reports a deadline shortfall naming it, and a client that compared a
deadline against a capacity of its own would put a task at risk on one surface and fine on another.
So the count is read and printed, and nothing here derives one.

**A task's own at-risk mark is read as absent-is-false**, which is the same smaller claim the
verdict reader makes. The header count is on the contract today and the per-task field is arriving;
reading it optionally means the marker appears the day the field does, and a build without it prints
a backlog rather than refusing one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from syncr_cli.wire.reading import (
    JsonMapping,
    boolean,
    integer,
    mapping,
    mappings,
    nested,
    optional_instant,
    text,
)

if TYPE_CHECKING:
    from datetime import datetime

BACKLOG_PATH = "backlog"


@dataclass(frozen=True, slots=True)
class Task:
    """One task, with the two figures the backlog renders that no column holds."""

    id: str
    area_id: str
    title: str
    estimate_minutes: int
    recorded_minutes: int
    remaining_minutes: int
    deadline: datetime | None
    priority: str
    status: str
    eligible_for_solving: bool
    at_risk: bool
    payload: JsonMapping

    @classmethod
    def read(cls, payload: JsonMapping, path: str) -> Self:
        return cls(
            id=text(payload, "id", path),
            area_id=text(payload, "areaId", path),
            title=text(payload, "title", path),
            estimate_minutes=integer(payload, "estimateMinutes", path),
            recorded_minutes=integer(payload, "recordedMinutes", path),
            remaining_minutes=integer(payload, "remainingMinutes", path),
            deadline=optional_instant(payload, "deadline", path),
            priority=text(payload, "priority", path),
            status=text(payload, "status", path),
            eligible_for_solving=boolean(payload, "eligibleForSolving", path),
            at_risk=_at_risk(payload, path),
            payload=payload,
        )

    @classmethod
    def read_one(cls, body: object, path: str) -> Self:
        """One task, as a capture or a completion answers with it."""
        return cls.read(mapping(body, path), path)


def _at_risk(payload: JsonMapping, path: str) -> bool:
    """Whether the current verdict reports a deadline shortfall naming this task.

    Absent reads as false rather than being required. The header's count is on the contract and the
    per-task field is arriving with the probe that produces it, so the smaller claim is the one a
    later contract is less likely to falsify: a build reading a response without the field prints a
    backlog rather than refusing one, and the marker appears the day the field does.

    Present and not a boolean is refused, because that is a contract violation rather than an
    absence.
    """
    if payload.get("atRisk") is None:
        return False
    return boolean(payload, "atRisk", path)


@dataclass(frozen=True, slots=True)
class Backlog:
    """The tasks a read selected, and the header counts that describe them."""

    open_count: int
    at_risk_count: int
    tasks: tuple[Task, ...]
    payload: JsonMapping

    @classmethod
    def read(cls, body: object) -> Self:
        payload = mapping(body, BACKLOG_PATH)
        header = nested(payload, "header", BACKLOG_PATH)
        return cls(
            open_count=integer(header, "openCount", f"{BACKLOG_PATH}.header"),
            at_risk_count=integer(header, "atRiskCount", f"{BACKLOG_PATH}.header"),
            tasks=tuple(
                Task.read(entry, f"{BACKLOG_PATH}.tasks[{index}]")
                for index, entry in enumerate(mappings(payload, "tasks", BACKLOG_PATH))
            ),
            payload=payload,
        )
