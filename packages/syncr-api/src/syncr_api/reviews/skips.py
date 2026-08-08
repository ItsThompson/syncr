"""Chronic skips: the run of weeks in which one item was proposed and then skipped.

``US-REV-02``: an item proposed and skipped for six consecutive weeks is raised in the weekly
session, stating the item and the number of consecutive weeks, and **syncr never reduces its
priority or removes it automatically**. Whether to reschedule, reduce scope, or drop is left to the
user, so nothing here writes and nothing here ranks: it counts weeks and names the item.

## Only a CONFIRMED skip counts, and the narrowing is the same one debt takes

An unconfirmed block is ``presumed``, and presuming a week and then reporting it as behaviour is how
a review comes to escalate something the user actually did. ``syncr_domain.debt`` states the same
narrowing for the same reason, and it has the same consequence: a user who stops confirming days
raises no chronic skip. That is deliberate. What tells them the review rests on nothing is the
confirmed-day count beside it.

## The group drops the occurrence key, and that is what makes a run computable

A binding names the content, which occurrence of it, and which chunk of a split task. The occurrence
key is scoped to its own week -- an index in expansion order, or a date -- so two occurrences of one
habit in two weeks never share one. Grouping on the whole binding would find a run of one every
time. :attr:`syncr_domain.identity.BindingRef.content_key` is that grouping, and repeated-pin
promotion groups on the same value for the same reason.

**Two skips of one item in one week are one week of evidence.** The run counts WEEKS, so a habit
skipped four times in one week is not four weeks behind.

## Consecutive means consecutive, and a week that proposed nothing breaks the run

The run is :func:`syncr_domain.weeks.longest_consecutive_run`, which is the one statement of it.
This and repeated-pin promotion are two raises counting the same thing, and a user reading two
different counts of it has no way to tell which is right. A week that did not propose the item holds
no skip of it, so it ends the run: the story's words are "proposed and skipped", and an item the
plan stopped offering is not one the user kept declining.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_domain.outcomes import OutcomeState
from syncr_domain.weeks import longest_consecutive_run

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from syncr_api.reviews.history import ReviewedWeek
    from syncr_domain.identity import BindingKind, BindingRef
    from syncr_domain.weeks import IsoWeek

    # What `BindingRef.content_key` answers: the binding with its week-scoped occurrence dropped.
    type ContentKey = tuple[BindingKind, UUID, int | None]


@dataclass(frozen=True, slots=True, kw_only=True)
class ChronicSkip:
    """One item the plan kept proposing and the user kept skipping.

    ``weeks`` is every ISO week of the run, in order, so the raise says "six consecutive weeks"
    from the data rather than from the threshold it passed. ``title`` is the name the block carried
    in the most recent of them, which is what the reader last saw on the grid.
    """

    binding: BindingRef
    title: str
    weeks: tuple[IsoWeek, ...]

    @property
    def consecutive_weeks(self) -> int:
        """How many weeks this run covers."""
        return len(self.weeks)


def chronic_skips(weeks: Sequence[ReviewedWeek], *, consecutive_weeks: int) -> list[ChronicSkip]:
    """Every item skipped in a run of at least ``consecutive_weeks`` weeks, longest run first.

    ``weeks`` is the reviewed window oldest first, which is the order the reader hands it in and the
    order a run is walked in.

    The longest run is what a group reports, for the reason promotion detection takes the longest:
    the raise is about the pattern, and reporting a nine-week run as three overlapping six-week ones
    is the nag the product's severity discipline forbids. A run longer than the window is reported
    as the window, which is the honest bound: the read covers a fixed number of weeks and cannot see
    past it.
    """
    skipped: dict[ContentKey, list[IsoWeek]] = {}
    named: dict[ContentKey, tuple[BindingRef, str]] = {}
    for week in weeks:
        for binding, title in _skipped_in(week).items():
            key = binding.content_key
            skipped.setdefault(key, []).append(week.iso_week)
            named[key] = (binding, title)
    found = []
    for key, weeks_skipped in skipped.items():
        run = longest_consecutive_run(weeks_skipped)
        if len(run) < consecutive_weeks:
            continue
        binding, title = named[key]
        found.append(ChronicSkip(binding=binding, title=title, weeks=run))
    return sorted(found, key=lambda one: (-one.consecutive_weeks, one.title))


def _skipped_in(week: ReviewedWeek) -> Mapping[BindingRef, str]:
    """Each item this week both proposed and recorded a confirmed skip for, with its title.

    A mapping rather than a list, because two occurrences of one habit in one week are one week of
    evidence and collapsing them here is what makes the count a count of weeks.
    """
    found: dict[BindingRef, str] = {}
    for day in week.days:
        for block in day.blocks:
            recorded = week.outcomes.get(str(block.id))
            if recorded is None or not recorded.is_confirmed:
                continue
            if recorded.state is OutcomeState.SKIPPED:
                found[block.binding] = block.title
    return found
