"""The four arms of the diff, and the two states a real write target holds that a diff must survive.

The reconciliation is a pure function over two sets, so it is driven here directly rather than
through a provider: what is asserted is which writes it decides on, and every case that decides one.

Four groups.

**The four arms.** In desired and not existing inserts; in both and differing patches; in existing
and not desired deletes; in existing with no syncr key deletes and counts as foreign. Each is driven
on its own, and then all four together, because a diff that got one arm right in isolation and
dropped it in company would pass four tests.

**Identical is the fifth arm and the common one.** An event already saying what syncr intends
produces no write at all, which is what makes an ordinary reconciliation cheap and what keeps a
destructive path off a calendar it need not touch.

**What decides "differing".** Every field a reader sees, one at a time, so a patch cannot be skipped
because one of them was left out of the comparison. And NOT the key, which decides which event this
is.

**Two events under one key.** Duplicating an event in a calendar client copies its private extended
properties, so a key is not unique on the target however carefully syncr writes. The resolution is
deterministic and idempotent: one holder is kept, the rest are removed, and a second pass finds
nothing left to do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syncr_api.calendars.projection import ProjectedEvent
from syncr_api.calendars.reconciliation import ExistingEvent, plan_reconciliation
from syncr_domain.intervals import Interval

NINE = datetime(2026, 2, 9, 9, tzinfo=UTC)
AN_HOUR = timedelta(hours=1)

KEY = "a" * 64
OTHER_KEY = "b" * 64


def intended(
    key: str = KEY,
    *,
    interval: Interval | None = None,
    title: str = "Gym · Legs",
    description: str | None = "Chosen by the rotation: Gym · Legs",
    location: str | None = None,
) -> ProjectedEvent:
    return ProjectedEvent(
        syncr_key=key,
        interval=interval or Interval(NINE, NINE + AN_HOUR),
        title=title,
        description=description,
        location=location,
    )


def held(event: ProjectedEvent, *, event_id: str = "evt-1") -> ExistingEvent:
    """The target holding exactly what syncr intends, which is the no-write case."""
    return ExistingEvent(
        event_id=event_id,
        interval=event.interval,
        syncr_key=event.syncr_key,
        title=event.title,
        description=event.description,
        location=event.location,
    )


def by_hand(event_id: str = "evt-user") -> ExistingEvent:
    """An event the user created in a calendar client: no key was ever written into it."""
    return ExistingEvent(
        event_id=event_id,
        interval=Interval(NINE, NINE + AN_HOUR),
        syncr_key=None,
        title="Dentist",
    )


def desired_of(*events: ProjectedEvent) -> dict[str, ProjectedEvent]:
    return {event.syncr_key: event for event in events}


# --------------------------------------------------------------------------------
# The four arms
# --------------------------------------------------------------------------------


def test_in_desired_and_not_existing_inserts() -> None:
    event = intended()

    plan = plan_reconciliation(desired_of(event), [])

    assert plan.inserts == (event,)
    assert plan.patches == ()
    assert plan.deletes == ()


def test_in_both_and_differing_patches() -> None:
    event = intended()
    moved = intended(interval=Interval(NINE + AN_HOUR, NINE + 2 * AN_HOUR))

    plan = plan_reconciliation(desired_of(moved), [held(event, event_id="evt-7")])

    assert [(patch.event_id, patch.intended) for patch in plan.patches] == [("evt-7", moved)]
    assert plan.inserts == ()
    assert plan.deletes == ()


def test_in_existing_and_not_desired_deletes() -> None:
    plan = plan_reconciliation({}, [held(intended(), event_id="evt-9")])

    assert [(one.event_id, one.foreign) for one in plan.deletes] == [("evt-9", False)]
    assert plan.inserts == ()
    assert plan.patches == ()


def test_in_existing_with_no_syncr_key_deletes_and_is_foreign() -> None:
    plan = plan_reconciliation({}, [by_hand()])

    assert [(one.event_id, one.foreign) for one in plan.deletes] == [("evt-user", True)]


def test_an_event_the_user_created_is_removed_even_while_the_plan_holds_its_slot() -> None:
    """Destructive within the horizon: a hand-made event is drift whatever else is there."""
    event = intended()

    plan = plan_reconciliation(desired_of(event), [by_hand()])

    assert plan.inserts == (event,)
    assert [one.foreign for one in plan.deletes] == [True]


def test_all_four_arms_at_once() -> None:
    unchanged = intended(KEY)
    to_patch = intended(OTHER_KEY, title="Leetcode")
    to_insert = intended("c" * 64, title="Prep for Kontron Interview")
    stale = held(intended("d" * 64), event_id="evt-stale")

    plan = plan_reconciliation(
        desired_of(unchanged, to_patch, to_insert),
        [
            held(unchanged, event_id="evt-1"),
            held(intended(OTHER_KEY, title="Leetcode (old)"), event_id="evt-2"),
            stale,
            by_hand("evt-user"),
        ],
    )

    assert plan.unchanged == 1
    assert [patch.event_id for patch in plan.patches] == ["evt-2"]
    assert plan.inserts == (to_insert,)
    assert sorted((one.event_id, one.foreign) for one in plan.deletes) == [
        ("evt-stale", False),
        ("evt-user", True),
    ]
    assert plan.writes == 4


# --------------------------------------------------------------------------------
# Identical writes nothing
# --------------------------------------------------------------------------------


def test_an_event_already_correct_produces_no_write() -> None:
    event = intended()

    plan = plan_reconciliation(desired_of(event), [held(event)])

    assert plan.writes == 0
    assert plan.unchanged == 1


def test_a_whole_horizon_already_correct_produces_no_write_at_all() -> None:
    """The steady state after a reconciliation, and why the thirty-second budget is reachable."""
    events = [intended(chr(ordinal) * 64) for ordinal in range(ord("a"), ord("a") + 20)]

    plan = plan_reconciliation(
        desired_of(*events),
        [held(event, event_id=f"evt-{index}") for index, event in enumerate(events)],
    )

    assert plan.writes == 0
    assert plan.unchanged == len(events)


# --------------------------------------------------------------------------------
# What decides "differing"
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "differing"),
    [
        ("interval", intended(interval=Interval(NINE + AN_HOUR, NINE + 2 * AN_HOUR))),
        ("title", intended(title="Gym · Push")),
        ("description", intended(description="Taken from the queue: Gym · Push")),
        ("location", intended(location="The gym")),
    ],
)
def test_a_difference_in_any_rendered_field_patches(field: str, differing: ProjectedEvent) -> None:
    """A field left out of the comparison would leave the phone showing a stale value forever."""
    plan = plan_reconciliation(desired_of(differing), [held(intended())])

    assert len(plan.patches) == 1, field
    assert plan.unchanged == 0


def test_a_difference_in_the_key_is_not_a_difference_but_a_different_event() -> None:
    """The key decides WHICH event this is, so a changed key is an insert plus a delete."""
    plan = plan_reconciliation(desired_of(intended(OTHER_KEY)), [held(intended(KEY))])

    assert len(plan.inserts) == 1
    assert len(plan.deletes) == 1
    assert plan.patches == ()


# --------------------------------------------------------------------------------
# Two events under one key
# --------------------------------------------------------------------------------


def test_a_duplicated_event_leaves_one_holder_and_removes_the_rest() -> None:
    event = intended()

    plan = plan_reconciliation(
        desired_of(event), [held(event, event_id="evt-b"), held(event, event_id="evt-a")]
    )

    assert plan.unchanged == 1
    assert [one.event_id for one in plan.deletes] == ["evt-b"]


def test_which_duplicate_is_kept_does_not_depend_on_the_order_the_provider_paged() -> None:
    event = intended()
    copies = [held(event, event_id="evt-b"), held(event, event_id="evt-a")]

    one_way = plan_reconciliation(desired_of(event), copies)
    other_way = plan_reconciliation(desired_of(event), list(reversed(copies)))

    assert one_way == other_way


def test_resolving_a_duplicate_is_idempotent() -> None:
    """A second pass over the target the first pass left finds nothing to do."""
    event = intended()
    kept = held(event, event_id="evt-a")

    first = plan_reconciliation(desired_of(event), [kept, held(event, event_id="evt-b")])
    second = plan_reconciliation(desired_of(event), [kept])

    assert [one.event_id for one in first.deletes] == ["evt-b"]
    assert second.writes == 0


def test_a_duplicate_of_a_key_syncr_no_longer_intends_removes_both() -> None:
    event = intended()

    plan = plan_reconciliation({}, [held(event, event_id="evt-a"), held(event, event_id="evt-b")])

    assert sorted(one.event_id for one in plan.deletes) == ["evt-a", "evt-b"]


def test_a_duplicate_carrying_syncrs_key_is_not_counted_as_foreign() -> None:
    """Whoever copied it, the event carries syncr's key, so removing it is not foreign."""
    event = intended()

    plan = plan_reconciliation(
        desired_of(event), [held(event, event_id="evt-a"), held(event, event_id="evt-b")]
    )

    assert [one.foreign for one in plan.deletes] == [False]


# --------------------------------------------------------------------------------
# The order the plan is applied in
# --------------------------------------------------------------------------------


def test_the_plan_states_its_own_application_order() -> None:
    """Patches, then inserts, then deletes: a partial application leaves a stale event rather than a
    gap where a commitment should be."""
    plan = plan_reconciliation(
        desired_of(intended(KEY, title="new"), intended("c" * 64)),
        [held(intended(KEY), event_id="evt-1"), held(intended("d" * 64), event_id="evt-2")],
    )

    assert plan.as_log_fields() == {
        "patch_count": 1,
        "insert_count": 1,
        "delete_count": 1,
        "unchanged_count": 0,
    }
