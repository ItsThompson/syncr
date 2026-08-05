"""A candidate concession's path to the worker: onto an operation as JSON, and back.

A tradeoff request must be evaluated against a concession that is **not yet persisted**, because
only approval writes one. The assembler takes it as an argument, so the candidate needs a channel of
its own from the request to the worker, and the operation is the only object that already crosses
that boundary. So it rides there as JSON, and this is the one place that shape is written and read.

Both directions live together for the reason the two task quantities do: a writer and a reader of
one shape in two modules is a shape that drifts, and the failure would be a concession the user
approved being read back as a different one, or as none.

**The reductions are the only interesting part.** They are per-date minutes, keyed by the local
date's ISO spelling, which is the same key a frame occurrence carries and the same key the stored
column holds: one spelling, so the fold pairs them without a second derivation. Reading is
deliberately tolerant of a key this week cannot honour and reports what it dropped, because a
document already written has to be readable; refusing one is the WRITE's job, and the concession
table's own upsert does it.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_api.plans.errors import AdjustmentRejected
from syncr_common.logging import get_logger
from syncr_domain.identity import date_occurrence_key
from syncr_domain.plan import AdjustmentKind
from syncr_solver.inputs import WeekAdjustment

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.zones import Date

_log = get_logger("syncr.plans")

# The keys the document carries. Named once, because a writer and a reader disagreeing about one of
# them is a concession that vanishes between the request and the solve.
ADJUSTMENT_ID: Final = "adjustmentId"
KIND: Final = "kind"
TARGET_ID: Final = "targetId"
REDUCTIONS: Final = "reductions"
DELTA_MINUTES: Final = "deltaMinutes"


def as_document(candidate: WeekAdjustment) -> dict[str, object]:
    """The candidate as the operation's own column carries it.

    Camel-cased like every other JSON shape this api writes, and flat: the document is read by one
    reader, in this application, and a nested shape would buy nothing but a second level to get
    wrong.
    """
    return {
        ADJUSTMENT_ID: str(candidate.adjustment_id),
        KIND: candidate.kind.value,
        TARGET_ID: str(candidate.target_id),
        REDUCTIONS: {
            date_occurrence_key(on): minutes for on, minutes in candidate.reductions.items()
        },
        DELTA_MINUTES: candidate.delta_minutes,
    }


def from_document(document: Mapping[str, object], *, dates: Sequence[Date]) -> WeekAdjustment:
    """The candidate an operation carries, as the value the assembler folds.

    Refused when the document does not describe a concession at all: the operation would otherwise
    solve the week WITHOUT the concession the user asked for and land a proposal that looks like it
    ignored them. A failed solve states why; a silently unhonoured one does not.
    """
    kind = _a_kind(document.get(KIND))
    return WeekAdjustment(
        adjustment_id=_an_identifier(document.get(ADJUSTMENT_ID), named=ADJUSTMENT_ID),
        kind=kind,
        target_id=_an_identifier(document.get(TARGET_ID), named=TARGET_ID),
        reductions=reductions_of(_a_mapping(document.get(REDUCTIONS)), dates=dates),
        delta_minutes=_a_figure(document.get(DELTA_MINUTES)),
    )


def reductions_of(stored: Mapping[str, object], *, dates: Sequence[Date]) -> Mapping[Date, int]:
    """The per-date minutes a routine reduction carries, as dates of THIS week.

    An entry this week cannot honour is dropped and reported, and there are three of them: a key
    that is not a date, a value that is not a count of minutes, and a date the week does not hold.
    All three have one consequence, which is a reduction that pairs with no frame occurrence and is
    applied to nothing while the concession claims to have been honoured. They are reported
    separately because the causes differ: the first two are malformed and the third is a readable
    date that another week's assembly owns, and an operator reading one event name should not go
    hunting for the other fault.
    """
    week = set(dates)
    reductions: dict[Date, int] = {}
    malformed: list[str] = []
    foreign: list[str] = []
    for key, value in stored.items():
        on = _a_date(key)
        if on is None or isinstance(value, bool) or not isinstance(value, int):
            malformed.append(key)
            continue
        if on not in week:
            foreign.append(key)
            continue
        reductions[on] = value
    if malformed:
        _log.warning("plans.adjustment.unreadable_reduction", entries=len(malformed))
    if foreign:
        _log.warning("plans.adjustment.reduction_outside_the_week", entries=len(foreign))
    return reductions


def _a_date(key: str) -> Date | None:
    try:
        return date.fromisoformat(key)
    except ValueError:
        return None


def _a_kind(value: object) -> AdjustmentKind:
    try:
        return AdjustmentKind(str(value))
    except ValueError as error:
        raise AdjustmentRejected(
            f"{value!r} is not one of the four concessions a tradeoff can persist"
        ) from error


def _an_identifier(value: object, *, named: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as error:
        raise AdjustmentRejected(f"{named} {value!r} is not an identifier") from error


def _a_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _a_figure(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdjustmentRejected(f"{DELTA_MINUTES} {value!r} is not a count of minutes")
    return value
