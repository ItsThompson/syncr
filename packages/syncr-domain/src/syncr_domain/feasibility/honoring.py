"""What a refusal says: the words a shortfall names its honored constraints in.

Separated from the arithmetic because it is a different subject. The checks decide whether there is
a gap and how large it is; this module decides what the user reads, and every entry here is a phrase
rather than a figure. Nothing in it can change a verdict.

Three rules govern the wording, and each exists because the alternative was worse:

*Only a constraint that took capacity from the window a check measured is named.* Occupancy wholly
behind ``now`` took nothing, so honoring it would name a constraint that did not produce the gap.
The overlap is measured against the window rather than against free capacity, so a term lying wholly
inside another is still named: it is a constraint the user holds, and which of two overlapping spans
took a minute is not a question a list of names has to answer.

*A duration is rendered and an instant is not.* The product's wording for a duration is one wording,
and the same figure appears in a shortfall's honored constraint and in the label of the tradeoff
offered against it. Rendering ``Fri 09:00`` would need the zone the user is in that day, which this
package deliberately cannot reach, so an earlier demand is named by its task and a surface renders
the deadline itself.

*The capacity the check measured against is always named, last.* It is what makes the honored list
non-empty on the one week where no other constraint applies, which is a fresh tenant whose declared
floors exceed the week. Without it the shortfall's own guard would raise on that input, on the
request path, in a component with no degraded mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.feasibility.verdict import hours_and_minutes
from syncr_domain.intervals import IntervalSet

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.feasibility.inputs import DeadlineDemand, ProbeInputs


def occupancy_honored(inputs: ProbeInputs) -> tuple[str, ...]:
    """What the week has already spent inside the capacity window, named for the user."""
    capacity = IntervalSet([inputs.span]).after(inputs.now)
    stated = (
        ("the circadian frame", inputs.frame),
        ("your external commitments", inputs.anchors),
        ("the time reserved around them", inputs.absolute_forbidden),
        ("the days you declared off-plan", inputs.off_plan),
        ("the time already committed to this week's plan", inputs.placed),
    )
    return tuple(label for label, occupied in stated if occupied.intersect(capacity))


def demands_honored(demands: Sequence[DeadlineDemand]) -> tuple[str, ...]:
    """The tasks a set of demands names, deduplicated in the order they arrive."""
    named: dict[str, None] = {}
    for demand in demands:
        for label in demand.labels:
            named.setdefault(label, None)
    return tuple(named)


def floor_honored(*, label: str, reserved_minutes: int) -> str:
    """One Area's floor, named as a constraint that took capacity from another Area's window.

    The phrase has two readers rather than one, which is why it is a function rather than an
    f-string at its single call site. A shortfall names the floor, and a tradeoff enumerator
    matches against that name to decide which floors are worth offering to breach: a shortfall
    carries no identifier for the floors it honored, and this list is the record of which ones
    took capacity from the window the check measured. Spelled in two places, the two spellings
    would drift and the enumerator would offer a breach that recovers nothing.
    """
    return f"the {label} floor of {hours_and_minutes(reserved_minutes)}"


def demands_due_no_later(demand: DeadlineDemand) -> tuple[str, ...]:
    """One demand's tasks, named as work that cannot wait past the deadline being measured.

    Read by a later deadline's shortfall: an earlier one has already claimed capacity, and this is
    how the user is told which work took it.
    """
    return tuple(f"{label}, due no later than this" for label in demand.labels)
