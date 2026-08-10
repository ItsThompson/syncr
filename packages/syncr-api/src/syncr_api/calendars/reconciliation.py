"""The diff: what syncr intends against what the write target holds, paired on the key alone.

```
in desired, not existing        → insert
in both, differing              → patch
in both, identical              → nothing at all
in existing, not desired        → DELETE
in existing, no syncr key       → DELETE, and count it as foreign
```

**Keyed on ``syncr_key`` and nothing else.** Diffing on title and time would churn every event
whenever a title changed, and it would make a moved block look like a delete plus an insert: the
user would watch their calendar rewrite itself for a re-titled habit, and the phone would show a gap
where a move should have been.

**Identical is its own arm, and it is the common one.** An ordinary reconciliation after a re-solve
finds almost everything already correct and writes only what moved, which is what makes the
projection budget reachable and what stops a destructive path touching a calendar it need not.

**Two existing events can hold one key**, and the resolution is deterministic. Duplicating an event
in a calendar client copies its private extended properties, so a key is not unique on the target
however carefully syncr writes: one holder is kept and patched, and every other is deleted as an
event syncr no longer intends. The kept one is the lowest event id, so two runs over the same target
make the same choice and the second run finds nothing left to resolve.

**A duplicate on the DESIRED side is not resolved, it is refused.** It means syncr collected one
span twice rather than that the target drifted, and the live case is a span crossing the ISO week
boundary, which belongs to the week its start falls in.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.calendars.projection_errors import ProjectionKeysCollide

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syncr_api.calendars.projection import ProjectedEvent
    from syncr_domain.intervals import Interval


@dataclass(frozen=True, slots=True)
class ExistingEvent:
    """One event the write target already holds, reduced to what the diff reads.

    ``syncr_key`` is ``None`` for an event the user created by hand: nothing wrote a key into its
    extended properties, and inside the horizon that is what makes removing it a foreign deletion.

    ``interval`` is ``None`` for an event whose span syncr cannot read -- a provider answer that
    does not hold the shape a timestamp has. Such an event is still ON the target inside the
    horizon, so it still has to be reconciled: unkeyed it is removed like any other drift, and keyed
    it is rewritten to what syncr intends, which is what an unreadable span deserves.
    """

    event_id: str
    interval: Interval | None = None
    syncr_key: str | None = None
    title: str = ""
    description: str | None = None
    location: str | None = None

    def matches(self, intended: ProjectedEvent) -> bool:
        """Whether this event already says what syncr intends, so no write is needed.

        Compared over everything a reader sees, which is deliberately NOT the diff key: the key
        decides which event this is, and this decides whether it needs changing. An event whose span
        could not be read matches nothing, so it is rewritten rather than left as it is.
        """
        return (
            self.interval == intended.interval
            and self.title == intended.title
            and self.description == intended.description
            and self.location == intended.location
        )


@dataclass(frozen=True, slots=True)
class DeleteRequest:
    """One event to remove from the target, and whether the user created it.

    The two are counted separately and removed identically, so the decision is made once, where the
    key is read, rather than by whatever applies the answer.
    """

    event_id: str
    foreign: bool = False


@dataclass(frozen=True, slots=True)
class Patch:
    """One event the target holds under the right key, and what syncr now intends it to say."""

    event_id: str
    intended: ProjectedEvent


@dataclass(frozen=True, slots=True)
class ReconciliationPlan:
    """The writes one reconciliation will make, computed whole before any of it is sent.

    Ordered as it is applied: patches, then inserts, then deletes. A partial application therefore
    leaves the target holding everything the plan wants plus a stale event the next reconciliation
    removes, rather than a gap where a commitment should be. Nothing the plan wants goes missing
    because a later write failed.
    """

    patches: tuple[Patch, ...] = ()
    inserts: tuple[ProjectedEvent, ...] = ()
    deletes: tuple[DeleteRequest, ...] = ()
    unchanged: int = 0

    @property
    def writes(self) -> int:
        """How many provider calls applying this plan will make."""
        return len(self.patches) + len(self.inserts) + len(self.deletes)

    def as_log_fields(self) -> dict[str, int]:
        """This plan as log fields, under names the redactor does not eat."""
        return {
            "patch_count": len(self.patches),
            "insert_count": len(self.inserts),
            "delete_count": len(self.deletes),
            "unchanged_count": self.unchanged,
        }


def plan_reconciliation(
    desired: Sequence[ProjectedEvent], existing: Iterable[ExistingEvent]
) -> ReconciliationPlan:
    """The four arms of the diff, over one horizon's worth of each side.

    ``existing`` is whatever the provider answered, so it may hold two events under one key and
    events under no key at all. ``desired`` is syncr's own, so two events under one key there is a
    fault in syncr and is refused rather than resolved.
    """
    intended = _keyed_by_syncr_key(desired)
    keyed, foreign = _partitioned(existing)
    patches: list[Patch] = []
    deletes = [DeleteRequest(event.event_id, foreign=True) for event in foreign]
    unchanged = 0
    for key, holders in keyed.items():
        wanted = intended.get(key)
        kept, duplicates = holders[0], holders[1:]
        # A duplicate of a key syncr still intends is as unintended as one of a key it does not, so
        # both leave through the same arm. Counted as a syncr deletion rather than a foreign one:
        # the event carries syncr's key, whoever copied it.
        deletes.extend(DeleteRequest(event.event_id) for event in duplicates)
        if wanted is None:
            deletes.append(DeleteRequest(kept.event_id))
        elif kept.matches(wanted):
            unchanged += 1
        else:
            patches.append(Patch(kept.event_id, wanted))
    return ReconciliationPlan(
        patches=tuple(patches),
        inserts=tuple(event for key, event in intended.items() if key not in keyed),
        deletes=tuple(deletes),
        unchanged=unchanged,
    )


def _keyed_by_syncr_key(desired: Sequence[ProjectedEvent]) -> dict[str, ProjectedEvent]:
    """The events syncr intends, by key, refusing two that claim one key.

    Refused rather than resolved because the two are indistinguishable to a diff: it would pair one
    of them and never see the other, so whichever lost would silently stop reaching the phone.
    """
    intended: dict[str, ProjectedEvent] = {}
    for event in desired:
        held = intended.get(event.syncr_key)
        if held is not None:
            raise ProjectionKeysCollide(
                f"two events syncr intends share the key {event.syncr_key!r}: "
                f"{held.title!r} at {held.interval.start} and {event.title!r} at "
                f"{event.interval.start}. One binding produces one block per week, so a shared key "
                "means a span was collected twice: a boundary-crossing block belongs to the week "
                "its start falls in and is emitted from that week alone"
            )
        intended[event.syncr_key] = event
    return intended


def _partitioned(
    existing: Iterable[ExistingEvent],
) -> tuple[dict[str, list[ExistingEvent]], list[ExistingEvent]]:
    """The target's events by key, and the ones carrying none.

    Each key's holders are ordered by event id, so which one is kept is a property of the target
    rather than of the order a provider happened to page its answer in.
    """
    keyed: defaultdict[str, list[ExistingEvent]] = defaultdict(list)
    foreign: list[ExistingEvent] = []
    for event in existing:
        if event.syncr_key is None:
            foreign.append(event)
        else:
            keyed[event.syncr_key].append(event)
    return {key: sorted(holders, key=_by_event_id) for key, holders in keyed.items()}, foreign


def _by_event_id(event: ExistingEvent) -> str:
    return event.event_id
