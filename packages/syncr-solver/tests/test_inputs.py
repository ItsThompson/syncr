"""``SolveInputs`` itself: what it carries, what it refuses, and what it cannot be asked.

The struct is the shared vocabulary of the solver, the probe, the materializer, and the
failure-reproduction runbook, so three of these tests are stated over its field inventory rather
than over a behaviour. That is deliberate: the defect this struct has had three times is a field
being read as two quantities, and the shape of the fix is always a pair. A test bounded by the
inventory fails when a pair is merged, which is the moment the defect is introduced rather than the
moment a verdict is wrong.

The rest is arithmetic that has to be reproducible: the seed a solve draws from, and the two
refusals that keep an assembly comparable to another assembly of the same instant.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from syncr_domain.identity import date_occurrence_key
from syncr_domain.intervals import Interval, IntervalError, IntervalSet
from syncr_domain.plan import PlanDocument, PlanError
from syncr_domain.templates import BindingTarget, TemplateEntryKind
from syncr_domain.weeks import IsoWeek
from syncr_solver.inputs import (
    AreaBudget,
    ChurnBaseline,
    DeadlineDemand,
    EligibleTask,
    EntryBinding,
    FrameEntry,
    HabitOccurrence,
    MaterializedEntry,
    ResolvedPreference,
    SolveInputs,
    frame_occupancy,
)

if TYPE_CHECKING:
    from syncr_domain.zones import Date, ZoneId

WEEK = IsoWeek(2026, 7)
LONDON = "Europe/London"
MONDAY_MIDNIGHT = datetime(2026, 2, 9, tzinfo=UTC)
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)

# Where the probe's demand is computed from. Neither figure appears anywhere on this struct, which
# is what makes that quantity impossible to derive inside a projection of it.
FIGURES_A_PROJECTION_CANNOT_SEE = frozenset({"estimate_minutes", "recorded_minutes"})

MEMBER_TYPES = (
    FrameEntry,
    MaterializedEntry,
    EntryBinding,
    HabitOccurrence,
    EligibleTask,
    DeadlineDemand,
    AreaBudget,
    ResolvedPreference,
    ChurnBaseline,
)


def zones(*, week: IsoWeek = WEEK, zone: ZoneId = LONDON) -> dict[Date, ZoneId]:
    return dict.fromkeys(week.dates(), zone)


def inputs(**overrides: object) -> SolveInputs:
    stated: dict[str, object] = {
        "iso_week": WEEK,
        "span": Interval(MONDAY_MIDNIGHT, MONDAY_MIDNIGHT + timedelta(days=7)),
        "now": NOW,
        "zone_by_date": zones(),
        "input_version": 3,
    }
    stated.update(overrides)
    return SolveInputs(**stated)  # type: ignore[arg-type]


def test_the_struct_carries_every_field_a_solve_and_a_probe_read() -> None:
    # An equality rather than a containment, so a field that goes away has to go from the readers
    # that name it, and the two quantity pairs cannot be merged into one field each without
    # failing here.
    assert {field.name for field in dataclasses.fields(SolveInputs)} == {
        "iso_week",
        "span",
        "now",
        "zone_by_date",
        "input_version",
        "frame",
        "frame_overhang",
        "anchors",
        "shadow_blocks",
        "dropped_legs",
        "forbidden_windows",
        "off_plan",
        "template_entries",
        "habit_occurrences",
        "eligible_tasks",
        "areas",
        "preferences",
        "pins",
        "deadline_demands",
        "adjustments",
        "live_plan",
        "churn_baseline",
    }


def test_no_member_type_carries_an_estimate_or_a_recorded_figure() -> None:
    # The claim that the probe's demand is not derivable from this struct, asserted rather than
    # stated: computing it needs a task's estimate and its recorded minutes, so if either ever
    # appears here, a later reader will derive the quantity in the projection and the two
    # consumers will disagree again.
    carried = {field.name for member in MEMBER_TYPES for field in dataclasses.fields(member)} | {
        field.name for field in dataclasses.fields(SolveInputs)
    }

    assert carried & FIGURES_A_PROJECTION_CANNOT_SEE == set()


def test_a_resolved_preference_carries_no_daily_cap() -> None:
    # The cap travels on the Area budget, which is what structurally prevents an override relaxing
    # a hard constraint: there is no field here that could carry one.
    assert "max_per_day_minutes" not in {
        field.name for field in dataclasses.fields(ResolvedPreference)
    }
    assert "max_per_day_minutes" in {field.name for field in dataclasses.fields(AreaBudget)}


def test_the_seed_is_derived_rather_than_supplied() -> None:
    # A value that can be supplied can be supplied wrongly, which is the same reason a block's id
    # is a property rather than a field.
    assert "seed" not in {field.name for field in dataclasses.fields(SolveInputs)}
    assert isinstance(inputs().seed, int)


def test_the_same_week_at_the_same_version_seeds_the_same_solve() -> None:
    assert inputs().seed == inputs().seed


def test_two_weeks_at_one_version_do_not_share_a_seed() -> None:
    # Without the week in the digest, every week a tenant has just created would solve from one
    # seed, so a tie broken by it would break the same way in each.
    following = WEEK.following()

    assert inputs().seed != inputs(iso_week=following, zone_by_date=zones(week=following)).seed


def test_a_bumped_version_seeds_a_different_solve() -> None:
    assert inputs().seed != inputs(input_version=4).seed


def test_the_instant_an_assembly_was_built_against_is_normalized_to_utc() -> None:
    # Two assemblies of one instant have to be equal, and a local reading of it would compare
    # equal to itself and unequal to the same instant expressed in another zone.
    local = NOW.astimezone(ZoneInfo(LONDON))

    assert inputs(now=local) == inputs(now=NOW)


def test_an_instant_carrying_no_zone_names_no_instant_and_is_refused() -> None:
    with pytest.raises(IntervalError):
        inputs(now=datetime(2026, 2, 11, 9, 0))  # noqa: DTZ001


def test_a_day_with_no_zone_resolves_its_wall_times_against_nothing_and_is_refused() -> None:
    partial = zones()
    partial.pop(WEEK.monday())

    with pytest.raises(PlanError):
        inputs(zone_by_date=partial)


def test_a_zone_for_a_day_the_week_does_not_hold_is_refused() -> None:
    foreign = zones()
    foreign[WEEK.following().monday()] = LONDON

    with pytest.raises(PlanError):
        inputs(zone_by_date=foreign)


def test_a_week_that_has_never_been_approved_states_that_rather_than_naming_a_revision() -> None:
    baseline = ChurnBaseline.never_approved()

    assert baseline.reason == ChurnBaseline.NEVER_APPROVED
    assert baseline.revision_id is None
    assert baseline.approved_at is None


def test_an_approved_baseline_names_the_revision_and_when_it_was_approved() -> None:
    identifier = uuid4()
    baseline = ChurnBaseline.approved(identifier, NOW)

    assert baseline.revision_id == identifier
    assert baseline.approved_at == NOW


def test_a_baseline_naming_a_revision_whose_plan_it_cannot_read_says_which_state_it_is_in() -> None:
    # The state a week is in when its approved document cannot be rebuilt. It is named rather than
    # reported as an ordinary approved baseline: a renderer told "approved-revision" would claim a
    # comparison against a plan nobody supplied.
    named = ChurnBaseline.approved(uuid4(), NOW)

    assert named.reason == ChurnBaseline.APPROVED_UNREADABLE
    assert named.is_measured is False


@pytest.mark.parametrize(
    ("revision_id", "approved_at"),
    [("an id", None), (None, NOW)],
    ids=["a revision with no instant", "an instant with no revision"],
)
def test_half_a_baseline_renders_half_a_sentence(
    revision_id: str | None, approved_at: object
) -> None:
    """The domain twin's rule, on this type too: the clause renders the date beside the revision."""
    with pytest.raises(PlanError, match="or neither"):
        ChurnBaseline(
            revision_id=None if revision_id is None else uuid4(),
            approved_at=approved_at,  # type: ignore[arg-type]
        )


def test_a_plan_no_revision_names_is_not_a_baseline() -> None:
    """The state a ``dominant`` clause citing churn could not render, so the type refuses it.

    ``is_measured`` reads the document, so a plan carried without a revision would make churn
    chargeable while ``reason`` still read ``never-approved``, and the clause would say the plan
    moved while naming nothing it moved from.
    """
    with pytest.raises(PlanError, match="names the revision that plan is"):
        ChurnBaseline(document=a_plan())


def test_an_approved_baseline_carrying_its_plan_is_what_churn_is_measured_against() -> None:
    # The other half of the guard above: the reachable three-field state is accepted.
    measured = ChurnBaseline.approved(uuid4(), NOW, a_plan())

    assert measured.reason == ChurnBaseline.APPROVED_REVISION
    assert measured.is_measured is True


def a_plan() -> PlanDocument:
    """An empty document of this week, for the baseline that carries one."""
    return PlanDocument(
        iso_week=WEEK,
        zone_by_date=dict.fromkeys(WEEK.dates(), LONDON),
        discretionary_minutes=0,
        unallocated_minutes=0,
        oversubscription_minutes=0,
    )


def test_an_assembly_defaults_to_a_week_holding_nothing() -> None:
    # The honest reading of a week nothing has planned: every collection is empty and the churn
    # baseline says there is no approved revision, rather than any of them being absent.
    empty = inputs()

    assert empty.frame == ()
    assert empty.eligible_tasks == ()
    assert empty.deadline_demands == ()
    assert empty.live_plan is None
    assert empty.churn_baseline.reason == ChurnBaseline.NEVER_APPROVED


def a_frame_entry(interval: Interval) -> FrameEntry:
    return FrameEntry(
        routine_id=uuid4(),
        occurrence_key="2026-02-09",
        interval=interval,
        min_duration_minutes=360,
        flex_band_minutes=30,
        title="Sleep",
    )


def test_the_frames_occupancy_is_this_weeks_occurrences_and_the_inherited_spans() -> None:
    # One question with one answer. A consumer reading `frame` alone would place work inside the
    # night the preceding week's occurrence already spent, which is the whole reason the
    # inherited spans are carried at all.
    monday_night = Interval(
        MONDAY_MIDNIGHT + timedelta(hours=23), MONDAY_MIDNIGHT + timedelta(hours=31)
    )
    inherited = Interval(MONDAY_MIDNIGHT, MONDAY_MIDNIGHT + timedelta(hours=7))

    occupied = inputs(
        frame=(a_frame_entry(monday_night),), frame_overhang=(inherited,)
    ).frame_occupancy()

    assert occupied == IntervalSet([inherited, monday_night])
    assert occupied.total_minutes() == 7 * 60 + 8 * 60


def test_the_struct_and_the_producer_read_one_statement_of_that_occupancy() -> None:
    # The producer needs the same union before the struct exists, because the discretionary
    # denominator subtracts the frame while the fields are still being resolved. Two statements
    # of it is how the denominator and the constraint checker would come to disagree.
    monday_night = Interval(
        MONDAY_MIDNIGHT + timedelta(hours=23), MONDAY_MIDNIGHT + timedelta(hours=31)
    )
    inherited = Interval(MONDAY_MIDNIGHT, MONDAY_MIDNIGHT + timedelta(hours=7))
    frame = (a_frame_entry(monday_night),)

    assert inputs(frame=frame, frame_overhang=(inherited,)).frame_occupancy() == frame_occupancy(
        frame, (inherited,)
    )


def test_an_inherited_span_reaching_outside_the_week_it_describes_is_refused() -> None:
    # The overhang is the part of the preceding week's occurrence that falls in THIS week, so a
    # member reaching past the span is the occurrence carried whole rather than clipped, and it
    # would subtract minutes this week does not hold from every figure taken over it.
    unclipped = Interval(MONDAY_MIDNIGHT - timedelta(hours=1), MONDAY_MIDNIGHT + timedelta(hours=7))

    with pytest.raises(PlanError):
        inputs(frame_overhang=(unclipped,))


def test_an_inherited_span_reaching_past_the_end_of_the_week_is_refused_too() -> None:
    # The mirror case, which a check written against the start alone would accept: the following
    # week owns whatever runs past this span's end.
    beyond = Interval(MONDAY_MIDNIGHT + timedelta(days=6), MONDAY_MIDNIGHT + timedelta(days=8))

    with pytest.raises(PlanError):
        inputs(frame_overhang=(beyond,))


def test_an_inherited_span_that_fills_the_whole_week_is_accepted() -> None:
    # A routine longer than a week is representable, and the bound is the span rather than a
    # duration, so an occurrence covering every minute of this week is inside it.
    whole = Interval(MONDAY_MIDNIGHT, MONDAY_MIDNIGHT + timedelta(days=7))

    assert inputs(frame_overhang=(whole,)).frame_overhang == (whole,)


# --------------------------------------------------------------------------------
# What a template entry of each kind carries
# --------------------------------------------------------------------------------


def an_entry(kind: TemplateEntryKind, **overrides: object) -> MaterializedEntry:
    stated: dict[str, object] = {
        "entry_id": uuid4(),
        "occurrence_key": date_occurrence_key(WEEK.monday()),
        "kind": kind,
        "interval": Interval(MONDAY_MIDNIGHT, MONDAY_MIDNIGHT + timedelta(minutes=15)),
        "flex_band_minutes": 0,
        "area_id": uuid4(),
    }
    stated.update(overrides)
    return MaterializedEntry(**stated)  # type: ignore[arg-type]


def test_a_concrete_entry_carries_the_content_it_names_and_the_name_of_it() -> None:
    binding = EntryBinding(target=BindingTarget.HABIT, entity_id=uuid4())

    entry = an_entry(TemplateEntryKind.CONCRETE, binding=binding, title="Shower")

    assert (entry.binding, entry.title) == (binding, "Shower")


def test_a_slot_carries_neither_a_binding_nor_a_name_because_nothing_is_chosen_yet() -> None:
    entry = an_entry(TemplateEntryKind.SLOT)

    assert (entry.binding, entry.title) == (None, None)


@pytest.mark.parametrize(
    ("kind", "overrides"),
    [
        (TemplateEntryKind.CONCRETE, {"title": "Shower"}),
        (
            TemplateEntryKind.CONCRETE,
            {"binding": EntryBinding(target=BindingTarget.HABIT, entity_id=uuid4())},
        ),
        (TemplateEntryKind.CONCRETE, {"binding": None, "title": ""}),
        (
            TemplateEntryKind.SLOT,
            {"binding": EntryBinding(target=BindingTarget.ROUTINE, entity_id=uuid4())},
        ),
        (TemplateEntryKind.SLOT, {"title": "Shower"}),
    ],
)
def test_half_a_content_statement_is_refused_whichever_half_it_is(
    kind: TemplateEntryKind, overrides: dict[str, object]
) -> None:
    # The block an entry becomes renders the resolved content name, so a name and the content it
    # names arrive together or neither does. Both directions, because each has its own failure: a
    # concrete entry missing either half cannot be placed, and a slot carrying either would be a
    # concrete entry claiming to bind late.
    with pytest.raises(PlanError):
        an_entry(kind, **overrides)


def test_an_entry_of_either_kind_carries_the_area_its_minutes_are_charged_to() -> None:
    # Required for both kinds, because a block that is neither the frame nor an anchor carries an
    # Area. For a concrete entry the producer resolves it from the content; there is no field for
    # "no Area", so an entry nothing can charge is not representable here.
    assert "area_id" in {field.name for field in dataclasses.fields(MaterializedEntry)}
    with pytest.raises(TypeError):
        MaterializedEntry(  # type: ignore[call-arg]
            entry_id=uuid4(),
            occurrence_key=date_occurrence_key(WEEK.monday()),
            kind=TemplateEntryKind.SLOT,
            interval=Interval(MONDAY_MIDNIGHT, MONDAY_MIDNIGHT + timedelta(minutes=15)),
            flex_band_minutes=0,
        )
