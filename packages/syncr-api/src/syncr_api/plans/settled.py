"""What the week has already lived, and which of it a candidate plan may not restate.

A block the week has reached appears in none of the authority classifier's output classes, so the
classes cannot protect it: each of them skips such a block and what persists is the candidate
DOCUMENT. An appended revision carries it whole, and so does the pending slot, whose document
becomes the plan of record on approval. So the pair of documents is compared directly here, and a
candidate that states a past the live plan does not is refused rather than repaired.

## The rule binds the placements the solve CHOSE, and only those

``syncr_domain.identity.PLACED_BY`` splits the seven origins in two, and this rule is stated over
one half of that split:

| Where the block's time came from | Bound by this rule |
|---|---|
| the solve chose it out of the time that was free: a habit, a task | **yes** |
| its source fixed it: a routine, a concrete entry, a commitment, a buffer | no |

A block the solve placed is a decision this product made, so placing it somewhere else after the
week has reached it is the product rewriting its own record of what happened. A block whose time a
declaration or an import fixes carries no decision at all: it restates a fact, and when the fact
changes the restatement changes with it.

**That narrowing is a decision rather than a convenience, and the alternative was measured.** The
guard's first draft bound all seven origins, on the premise that a well-behaved candidate satisfies
it for free because the solver may not move a block that has started. The premise is false: that
rule binds the solver's SEARCH, while ``syncr_solver.inheritance.inherited`` carries every derived
block at the span THIS week's derivation determined, whether or not the week has reached it. Two
ordinary upstream events therefore produce a disagreement no defect caused:

```
a commitment the user corrected in their calendar after it began
  live plan holds the anchor at   Wed 07:00-08:00     (now = Wed 09:00)
  the feed now says               Wed 07:30-08:30
  the candidate carries the corrected span, and the seven-origin rule refuses it

a routine edited mid-week whose occurrence has already begun
  live plan holds Sleep at        Tue 23:00-07:00     (started)
  the routine now states          Tue 23:00-06:30
  same refusal, same cause
```

Nothing reconciles the live plan's past with the corrected fact, so the refusal is permanent for
that week: every solve of it fails until it leaves the horizon, and extending a meeting that is in
progress is the most ordinary version of it.

**What the narrowing costs, stated plainly.** A corrected commitment's elapsed span replaces what
the week recorded, so the retro compares against the corrected fact rather than against what was
first imported. That is the same class of drift the content exemption below already accepts, and it
is the direction the source of truth points: the calendar is authoritative about the meeting.

**What it keeps.** A candidate that drops or moves a started habit or task block is still refused,
which is the shape a solve can produce by mistake and the whole subject of the rule.

**Two other answers were considered and are recorded so neither is re-invented.** Making the
calendar ingest path write a corrected past into the live plan would keep the rule at full width,
but it needs a new write that changes an already-elapsed placement plus its own rule about what a
correction may restate, and it covers only the commitment: a routine edited mid-week is not an
ingest at all, so that shape would still wedge. Filtering the assembler's anchor read by ``now``
is worse than either: the candidate then omits the started commitment, which reads as a drop and is
refused for the same reason, so it moves the wedge rather than removing it.

## Placements only, whatever the origin

What is compared is where each bound block sits and nothing about what it says. A block id is a
digest of the week and the binding, so a rename or a re-filing into another Area passes
deliberately: refusing it would stop a week's solving for the rest of that week, which is worse
than the drift. What the drift costs is that an elapsed hour can be re-attributed, and the Area is
what the retro and the unallocated figure read.

The comparison is symmetric, because both directions rewrite history: a block missing from the
candidate is one the week lived and the plan no longer places, and one the candidate holds in the
past that the live plan does not is time the user is told they spent on something nobody scheduled.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_api.plans.errors import ClassificationRejected
from syncr_domain.identity import is_placed_by_the_solver
from syncr_domain.intervals import has_elapsed, has_started

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.identity import BlockId
    from syncr_domain.intervals import Instant, Interval
    from syncr_domain.plan import PlanDocument

# How many block ids a refusal names before it counts the rest. A week holds hundreds of blocks and
# a message that listed every disagreeing one would be a log line nobody reads.
IDS_IN_A_REFUSAL: Final = 3


def require_an_unchanged_past(
    live: PlanDocument | None, candidate: PlanDocument, *, now: Instant
) -> None:
    """Both documents place the same started SOLVER-PLACED blocks alike, or this is refused.

    A week with no live plan has no past to restate, so a first plan for a week that is half
    elapsed is accepted as it stands.
    """
    if live is None:
        return
    settled = settled_placements(live, now)
    restated = settled_placements(candidate, now)
    stated = ", ".join(
        filter(
            None,
            (
                _named("dropped", sorted(settled.keys() - restated.keys())),
                _named("invented", sorted(_stated_past(restated, settled, now))),
                _named("moved", sorted(_relocated_in_the_past(settled, restated))),
            ),
        )
    )
    if not stated:
        return
    raise ClassificationRejected(
        f"the candidate for {candidate.iso_week} places a block the week has already reached "
        f"differently than the live plan does: {stated}. Where the solve put such a block is not a "
        "change this product may make, and the document is what becomes the plan of record, so the "
        "diff skipping the block cannot protect it"
    )


def settled_placements(document: PlanDocument, now: Instant) -> Mapping[BlockId, Interval]:
    """Where this document puts every block the solve placed that the week has reached.

    The origin filter is what bounds the rule, and it is read from the domain rather than kept as a
    set here: the same fact decides who may move a block in a conflict resolution, and two subsets
    of one vocabulary would come to disagree about which blocks the past protects.
    """
    return {
        block.id: block.interval
        for block in document.blocks
        if has_started(block.interval, now) and is_placed_by_the_solver(block.origin)
    }


def _stated_past(
    restated: Mapping[BlockId, Interval], settled: Mapping[BlockId, Interval], now: Instant
) -> list[BlockId]:
    """The blocks the candidate puts in the past that the live plan does not hold at all.

    A block beginning AT the reference instant is excluded, and that exclusion is the one place the
    two readings of "started" differ. The solver may place work beginning now, so binding this
    direction at the wider reading wedges the week at every assembly instant that falls on the
    placement grid: the guard reads the block as a past the live plan does not state, the operation
    fails, and the next trigger repeats it. Measured against the real solver at 09:00.

    The other two directions keep the wider reading, because both are about a block the LIVE plan
    holds: dropping or moving one is a rewrite whatever its elapsed length. So what this costs is a
    block beginning exactly now reaching the plan of record without appearing in a class, which is
    one instant of drift against a week that could not solve at all. The two boundaries are still
    not aligned, and no test in this package would notice if this one moved.
    """
    return [one for one in restated.keys() - settled.keys() if has_elapsed(restated[one], now)]


def _relocated_in_the_past(
    settled: Mapping[BlockId, Interval], restated: Mapping[BlockId, Interval]
) -> list[BlockId]:
    return [one for one in settled.keys() & restated.keys() if settled[one] != restated[one]]


def _named(verb: str, ids: list[BlockId]) -> str:
    """``verb`` and the blocks it happened to, bounded, because a week holds hundreds."""
    if not ids:
        return ""
    shown = ", ".join(ids[:IDS_IN_A_REFUSAL])
    more = "" if len(ids) <= IDS_IN_A_REFUSAL else f" and {len(ids) - IDS_IN_A_REFUSAL} more"
    return f"{verb} {shown}{more}"
