"""The replacement index, and the cross-form matching it serves.

A ``RECURRENCE-ID`` names one occurrence, and RFC 5545 permits it in more than one spelling: the
occurrence's own wall time in the series' zone, the same moment as UTC, and the same moment in any
other named zone. So matching a replacement to an occurrence cannot be done on the wall time alone,
and an index from the instant back to the keys is what reaches across the forms.

That index is where the two claims this module asserts live. It carries EVERY key that resolves onto
an instant, not one of them, and it carries each key ON the instant that key names. Each claim is
crossed against the components a body declares rather than counted, because a count over a corpus of
one shape cannot tell "every" from "one".

The behavioural half is driven on ``Pacific/Apia`` across 2011-12-30, the date the zone skipped
entirely. A one-hour daylight-saving gap collapses two walls an hour apart on one date, and no daily
rule produces both; a skipped DATE collapses the same time of day on two consecutive dates, which a
daily rule produces as two occurrences. Two occurrences on one instant is what makes the index's
answer observable, so the bodies here are permuted and the answer must not move.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from itertools import permutations
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import syncr_api.calendars.ics_partition as ics_partition_module
import syncr_api.calendars.ics_placement as ics_placement_module
from syncr_api.calendars.ics_components import read_component
from syncr_api.calendars.ics_errors import UNREPRESENTABLE, IcsRejection
from syncr_api.calendars.ics_lines import events_in, parse_components
from syncr_api.calendars.ics_parse import parse_feed
from syncr_api.calendars.ics_partition import Series, replaced_key, sort_components
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile
from tests.hostile_ics import (
    ALL_FEEDS,
    CROWDED_INSTANT,
    CROWDED_INSTANT_COMPONENTS,
    SKIPPED_DATE_COMPONENTS,
    SKIPPED_DATE_GAP,
    SKIPPED_DATE_IN_UTC_FORM,
    calendar_of,
)

if TYPE_CHECKING:
    from syncr_api.calendars.events import FetchOutcome
    from syncr_api.calendars.ics_components import EventComponent
    from syncr_api.calendars.ics_partition import OccurrenceKey

HOME = ZoneProfile(home_zone="Europe/London")

# The horizon February 2026's bodies are read against, so a corpus body answers here as it does
# everywhere else in the suite.
HORIZON = Interval(datetime(2026, 2, 9, tzinfo=UTC), datetime(2026, 2, 23, tzinfo=UTC))

# The days around the date `Pacific/Apia` skipped.
SKIPPED_DATE = Interval(datetime(2011, 12, 28, tzinfo=UTC), datetime(2012, 1, 2, tzinfo=UTC))

# Everything a component's own values can produce, which the parser's first pass reports rather
# than raising. Spelled from the package's own names so a helper here cannot drift from the set the
# parser catches: a member added there and missing here surfaces as a raise in these tests.
_REPORTABLE = (IcsRejection, *UNREPRESENTABLE)


def wall(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """A wall time, which carries no zone by definition: what a ``RECURRENCE-ID`` states."""
    return datetime(year, month, day, hour, minute)  # noqa: DTZ001 - wall time by definition


def _readable(body: str) -> list[EventComponent]:
    """Every component of ``body`` the package can read, as the parser's first pass reads them."""
    try:
        components = tuple(events_in(parse_components(body)))
    except _REPORTABLE:
        return []
    kept: list[EventComponent] = []
    for component in components:
        try:
            kept.append(read_component(component, HOME))
        except _REPORTABLE:
            continue
    return kept


def _sorted(body: str) -> Series:
    return sort_components(_readable(body))


def _carried(series: Series) -> list[OccurrenceKey]:
    """Every key the index holds, however many share an instant."""
    return [key for keys in series.same_instant.values() for key in keys]


def _declared_instants(body: str) -> dict[OccurrenceKey, set[datetime]]:
    """Every instant each key is declared at, read off the components rather than off the index."""
    declared: dict[OccurrenceKey, set[datetime]] = {}
    for component in _readable(body):
        if component.replaces_at is None:
            continue
        declared.setdefault(replaced_key(component), set()).add(component.replaces_at)
    return declared


def _answer(outcome: FetchOutcome) -> list[tuple[datetime, str]]:
    """What a body placed, as a list rather than a mapping.

    A list of pairs, because a component placed TWICE collapses into one entry under any mapping and
    the assertion then cannot see one replacement standing on two occurrences.
    """
    return sorted((event.interval.start, event.title) for event in outcome.events)


def _counts(outcome: FetchOutcome) -> tuple[int, int, int, int]:
    return (
        outcome.events_read,
        outcome.overrides_applied,
        outcome.duplicates_discarded,
        outcome.cancelled_discarded,
    )


# --------------------------------------------------------------------------------
# The index, crossed against the components rather than counted
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(ALL_FEEDS))
def test_the_index_carries_every_key_that_survived_sorting(label: str) -> None:
    # The first conjunct: EVERY key on an instant. Crossed against the keys sorting kept rather than
    # counted, because a body declaring one replacement per instant cannot tell a rule that carries
    # every key from one that carries the last.
    series = _sorted(ALL_FEEDS[label])

    carried = _carried(series)

    assert sorted(carried) == sorted(set(series.overrides) | series.tombstones.keys())
    # One entry per key, so a key reachable twice on one instant cannot pass the crossing above.
    assert len(carried) == len(set(carried))


@pytest.mark.parametrize("label", sorted(ALL_FEEDS))
def test_every_key_sits_on_an_instant_the_body_declares_for_it(label: str) -> None:
    # The second conjunct: ON one instant. The index is keyed by the series and the INSTANT a key
    # resolves onto, so an entry built from anything else -- the key's own wall time, the series
    # alone -- offers an occurrence a replacement belonging to a different moment.
    #
    # An instant the body declares for that key, not THE instant: two components can name one key in
    # two zones, so a key can be declared at more than one instant. Which of those the index should
    # file it under is a precedence question this does not answer.
    body = ALL_FEEDS[label]
    declared = _declared_instants(body)

    series = _sorted(body)

    for (uid, instant), keys in series.same_instant.items():
        for key in keys:
            assert key[0] == uid
            assert instant in declared[key], (label, key)


def test_the_corpus_reaches_an_instant_holding_more_than_one_key() -> None:
    # The crossings above are vacuous for a body that declares no replacement, and blind to the
    # difference between "every" and "one" for a body whose instants hold a single key. So the
    # corpus is measured for the shape that arms them, by BODY and by how many keys each crowded
    # instant holds: a corpus of two-key instants cannot tell "every key" from "the first two".
    crowded = {
        label: sorted(len(keys) for keys in _sorted(body).same_instant.values())
        for label, body in ALL_FEEDS.items()
    }

    armed = {label: sizes for label, sizes in crowded.items() if any(size > 1 for size in sizes)}

    assert armed == {
        # A one-hour gap collapses two walls onto one instant as readily as a skipped date does, so
        # the index holds two keys on an instant for this body as well. What this body cannot
        # produce is a lookup that consults them: both its keys are walls the series produces, so
        # each occurrence matches its own and the cross-form fallback is never reached.
        "spring_forward_gap": [2],
        "skipped_date_gap": [2],
        "crowded_instant": [3],
        # And every body this suite adds on purpose: one occurrence named in two legal forms, whose
        # instant holds exactly the own-wall key and the foreign-zone key.
        "one_occurrence_in_both_forms": [2],
        "one_occurrence_in_both_forms_reversed": [2],
        "cancelled_across_the_forms": [2],
        "cancelled_across_the_forms_reversed": [2],
        "cancelled_in_the_own_form": [2],
        "cancelled_in_the_own_form_reversed": [2],
    }


def test_the_index_holds_every_form_of_one_instant_beside_the_occurrences_own_wall() -> None:
    # Written out by hand rather than derived: the three RECURRENCE-ID values this body declares are
    # 20111230T190000Z, 20111231T090000 in Pacific/Apia, and 20111231T040000 in Asia/Tokyo, and all
    # three name the instant 2011-12-30T19:00Z. The index holds one entry, and that entry holds all
    # three keys in wall order.
    series = _sorted(CROWDED_INSTANT)

    assert series.same_instant == {
        ("apia@example.org", datetime(2011, 12, 30, 19, 0, tzinfo=UTC)): (
            ("apia@example.org", wall(2011, 12, 30, 19, 0)),
            ("apia@example.org", wall(2011, 12, 31, 4, 0)),
            ("apia@example.org", wall(2011, 12, 31, 9, 0)),
        )
    }


# --------------------------------------------------------------------------------
# What the index answers, under every permutation of declaration order
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("order", list(permutations(SKIPPED_DATE_COMPONENTS)))
def test_two_occurrences_on_one_instant_both_keep_their_replacement(order: tuple[str, ...]) -> None:
    # Two occurrences of one series share the instant 2011-12-30T19:00Z, and each carries a
    # replacement: the skipped date's in the UTC form, the day after's in its own wall form. Both
    # are reachable only if the instant carries both keys, and the answer must not depend on which
    # of them the publisher wrote last.
    outcome = parse_feed(calendar_of(*order), horizon=SKIPPED_DATE, profile=HOME)

    assert _answer(outcome) == [
        (datetime(2011, 12, 29, 19, 0, tzinfo=UTC), "Daily across the skipped date"),
        (datetime(2011, 12, 31, 2, 0, tzinfo=UTC), "Moved from the skipped date"),
        (datetime(2011, 12, 31, 4, 0, tzinfo=UTC), "Moved from the day after"),
    ]
    assert _counts(outcome) == (3, 2, 0, 0)
    # Three occurrences, three identities: a replacement standing on two of them would collapse one.
    assert len({event.uid for event in outcome.events}) == 3


_CANCELLED_ON_THE_SKIPPED_DATE = SKIPPED_DATE_IN_UTC_FORM.replace(
    "SUMMARY:Moved from the skipped date",
    "STATUS:CANCELLED\r\nSUMMARY:Cancelled on the skipped date",
)

_ONE_REPLACEMENT_ON_THE_INSTANT = (
    SKIPPED_DATE_COMPONENTS[0],
    SKIPPED_DATE_IN_UTC_FORM,
)

_A_CANCELLATION_ON_THE_INSTANT = (
    SKIPPED_DATE_COMPONENTS[0],
    SKIPPED_DATE_COMPONENTS[2],
    _CANCELLED_ON_THE_SKIPPED_DATE,
)


@pytest.mark.parametrize("order", list(permutations(CROWDED_INSTANT_COMPONENTS)))
def test_more_keys_than_occurrences_on_one_instant_still_answer_one_way(
    order: tuple[str, ...],
) -> None:
    # A third replacement on the same instant, named in a zone that is neither the series' nor UTC.
    # There are two occurrences to claim three keys, so one key goes unclaimed whatever happens, and
    # WHICH events are placed still cannot depend on declaration order. That is what ordering the
    # keys buys: an index in declaration order answers this body two ways.
    outcome = parse_feed(calendar_of(*order), horizon=SKIPPED_DATE, profile=HOME)

    assert _answer(outcome) == [
        (datetime(2011, 12, 29, 19, 0, tzinfo=UTC), "Daily across the skipped date"),
        (datetime(2011, 12, 31, 2, 0, tzinfo=UTC), "Moved from the skipped date"),
        (datetime(2011, 12, 31, 4, 0, tzinfo=UTC), "Moved from the day after"),
    ]
    # The unclaimed key is read and places nothing, which is the term that accounts for it.
    assert _counts(outcome) == (4, 2, 0, 0)
    assert outcome.unplaced == 1


@pytest.mark.parametrize("order", list(permutations(_ONE_REPLACEMENT_ON_THE_INSTANT)))
def test_one_replacement_on_a_crowded_instant_stands_on_one_occurrence_only(
    order: tuple[str, ...],
) -> None:
    # ONE replacement, in the UTC form, on an instant two occurrences share. The skipped date's
    # occurrence takes it across the forms; the day after's must keep its own event rather than a
    # second copy of that one component under a second identity.
    #
    # A one-hour gap cannot ask this question. There the UTC form states the same wall stamp as the
    # gap wall itself, so the occurrence sharing the instant is turned away by the walls the series
    # produces before anything else is consulted. Here the UTC form's wall is 19:00 on the skipped
    # date, which the series never produces, so what keeps the second occurrence off it is that the
    # key was already applied.
    outcome = parse_feed(calendar_of(*order), horizon=SKIPPED_DATE, profile=HOME)

    assert _answer(outcome) == [
        (datetime(2011, 12, 29, 19, 0, tzinfo=UTC), "Daily across the skipped date"),
        (datetime(2011, 12, 30, 19, 0, tzinfo=UTC), "Daily across the skipped date"),
        (datetime(2011, 12, 31, 2, 0, tzinfo=UTC), "Moved from the skipped date"),
    ]
    assert _counts(outcome) == (2, 1, 0, 0)
    assert len({event.uid for event in outcome.events}) == 3


@pytest.mark.parametrize("order", list(permutations(_A_CANCELLATION_ON_THE_INSTANT)))
def test_a_cancellation_on_a_crowded_instant_suppresses_only_its_own_occurrence(
    order: tuple[str, ...],
) -> None:
    # The tombstone half of the index, which is filed there on the same terms as a live override.
    # The cancellation names the skipped date in the UTC form; the occurrence sharing its instant
    # keeps the replacement written for it, and the occurrence before them both is untouched.
    outcome = parse_feed(calendar_of(*order), horizon=SKIPPED_DATE, profile=HOME)

    assert _answer(outcome) == [
        (datetime(2011, 12, 29, 19, 0, tzinfo=UTC), "Daily across the skipped date"),
        (datetime(2011, 12, 31, 4, 0, tzinfo=UTC), "Moved from the day after"),
    ]
    assert _counts(outcome) == (3, 2, 0, 0)


def test_the_skipped_date_body_places_nothing_under_the_corpus_horizon() -> None:
    # The corpus reads every body against February 2026, and this one is in December 2011. Its
    # components have to be accounted for there too, or the panel's arithmetic stops closing for the
    # feed that carries them.
    outcome = parse_feed(SKIPPED_DATE_GAP, horizon=HORIZON, profile=HOME)

    assert outcome.events == ()
    assert outcome.rejected == ()
    assert _counts(outcome) == (3, 0, 0, 0)
    assert outcome.unplaced == 3


# --------------------------------------------------------------------------------
# One precedence implementation, read out of the source rather than trusted
# --------------------------------------------------------------------------------

# The functions that MATCH a replacement to an occurrence, and the ones that RESOLVE which
# replacement stands. The rule lives only in the second set.
_MATCHING_FUNCTIONS = ("expand", "_named_by")
_RESOLVING_FUNCTIONS = ("_compete", "_resolve", "_across_forms")


def _module_functions() -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Function defs from both the partition and the placement modules."""
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for module in (ics_partition_module, ics_placement_module):
        assert module.__file__ is not None
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        functions.update(
            {
                node.name: node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            }
        )
    return functions


def test_precedence_is_decided_once_and_not_again_at_match_time() -> None:
    # Which replacement stands is settled where the keys compete, before any occurrence is matched.
    # A SECOND copy of the SEQUENCE comparison or the cancellation check pasted into the matching
    # path would still answer the corpus right -- the winners are already in place -- while quietly
    # re-deciding what resolution decided, so no behavioural input bites on it. What does bite is
    # reading the source: matching must be a lookup, and both resolution sites must drive the one
    # shared rule.
    functions = _module_functions()

    # A renamed function would silence every claim below, so the census names what it inspected.
    for name in (*_MATCHING_FUNCTIONS, *_RESOLVING_FUNCTIONS):
        assert name in functions, name

    for name in _MATCHING_FUNCTIONS:
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                assert not any(
                    isinstance(side, ast.Attribute) and side.attr == "sequence"
                    for compared in operands
                    for side in ast.walk(compared)
                ), f"{name} compares SEQUENCE at match time"
            if isinstance(node, ast.Attribute) and node.attr == "cancelled":
                # Deliberately broader than the defect it guards: any cancellation READ at match
                # time re-decides a precedence question here. A future read that looks legitimate
                # belongs in resolution, not in matching.
                raise AssertionError(f"{name} reads a cancellation at match time")

    for name in ("_resolve", "_across_forms"):
        called = {
            node.id
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        assert "_compete" in called, f"{name} runs its own precedence rule"
