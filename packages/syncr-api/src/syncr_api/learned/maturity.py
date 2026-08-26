"""The maturity list, read back out of the row the nightly job wrote.

The job writes an array of objects into ``weight_sets.maturity``; this is the reader. Both spellings
exist because the writer is in another package that must not import this one, and the learning
suite's agreement test crosses the keys in one process.

**An unreadable row is dropped and reported rather than failing the read.** The Learned screen is a
trust surface: a screen that returns 500 because one of eleven rows is malformed tells the user
nothing and hides the ten that are fine. What is NOT tolerated inside a row is a state that
disagrees with its own value, because that is the gate as the user reads it: a row claiming to be
ready with no figure would say the solver is applying something it is not.

**One freshness rule for the two strings a row says about an Area.** The ``plain_language`` sentence
is frozen at fit time: the fitter composes it once from that fit's figures, storage holds it
verbatim, and this reader passes it through untouched, so renaming the Area leaves the sentence
saying the name the fit knew. The subject follows the sentence rather than the rename for the same
reason in mirror: the row carries only the Area's identifier, so its name cannot be spelled from
storage at all and can only be resolved against the Areas the tenant holds when the row is read.
The two strings may therefore disagree after a rename, and that is the rule working: the sentence
reports the fit as it happened, the subject names what the row is about today.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Final, Literal

from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.core.columns import JsonObject

_log = get_logger("syncr.learned")

PARAMETER = "parameter"
SAMPLES = "samples"
THRESHOLD = "threshold"
STATE = "state"
VALUE = "value"
SHRINKAGE_WEIGHT = "shrinkage_weight"
PLAIN_LANGUAGE = "plain_language"

COLLECTING: Final = "collecting"
READY: Final = "ready"
STATES: Final = (COLLECTING, READY)


@dataclass(frozen=True, slots=True, kw_only=True)
class ParameterMaturityReading:
    """One row of the Learned screen, as the stored array holds it."""

    parameter: str
    samples: int
    threshold: int
    state: Literal["collecting", "ready"]
    value: float | None
    shrinkage_weight: float
    plain_language: str

    @property
    def is_ready(self) -> bool:
        """Whether the solver applies this parameter."""
        return self.state == READY


def maturity_rows(stored: Sequence[JsonObject]) -> tuple[ParameterMaturityReading, ...]:
    """Every row of a stored maturity array this deployment can read, in the order it holds them."""
    readable: list[ParameterMaturityReading] = []
    unreadable = 0
    for one in stored:
        row = _row(one)
        if row is None:
            unreadable += 1
            continue
        readable.append(row)
    if unreadable:
        _log.warning("learned.maturity.unreadable", rows=unreadable)
    return tuple(readable)


def _row(stored: object) -> ParameterMaturityReading | None:
    if not isinstance(stored, dict):
        return None
    state = stored.get(STATE)
    parameter = stored.get(PARAMETER)
    sentence = stored.get(PLAIN_LANGUAGE)
    samples = _a_count(stored.get(SAMPLES))
    threshold = _a_count(stored.get(THRESHOLD))
    weight = _a_share(stored.get(SHRINKAGE_WEIGHT))
    value = _a_number(stored.get(VALUE))
    if (
        not isinstance(parameter, str)
        or not isinstance(sentence, str)
        or state not in STATES
        or samples is None
        or threshold is None
        or weight is None
    ):
        return None
    # The gate as the user reads it. A ready row with no figure would say the solver is applying
    # something it is not, and a collecting row with one would offer a number nothing reads.
    if (state == READY) != (value is not None):
        return None
    return ParameterMaturityReading(
        parameter=parameter,
        samples=samples,
        threshold=threshold,
        state=READY if state == READY else COLLECTING,
        value=value,
        shrinkage_weight=weight,
        plain_language=sentence,
    )


def ready_count(rows: Sequence[ParameterMaturityReading]) -> int:
    """How many parameters the solver applies."""
    return sum(1 for row in rows if row.is_ready)


def collecting_count(rows: Sequence[ParameterMaturityReading]) -> int:
    """How many are still below their threshold, and therefore not applied at all."""
    return len(rows) - ready_count(rows)


def _a_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _a_share(value: object) -> float | None:
    number = _a_number(value)
    return number if number is not None and 0.0 <= number <= 1.0 else None


def _a_number(value: object) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if isfinite(value) else None


def statements_of(rows: Sequence[ParameterMaturityReading]) -> Mapping[str, str]:
    """Each row's plain-language sentence by the parameter it is about."""
    return {row.parameter: row.plain_language for row in rows}
