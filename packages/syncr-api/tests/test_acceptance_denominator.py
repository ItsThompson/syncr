"""Which edits reach the overridden half of the acceptance ratio, and what the panel says they are.

Three surfaces, because the figure is wrong in a different way at each: the count itself, the gauge
the panel draws, and the description an operator reads instead of this code. The exact ratios are
here rather than a direction, for the reason ``test_product_metrics`` states: a test that a ratio
"goes up" passes for a formula wrong by a factor.

The one case the narrowing does NOT reach is asserted too, in the panel's own words: a pin in a week
the solver never touched still counts, because nothing on the row says whether a solve had placed
the block.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final, assert_never
from uuid import uuid4

import pytest

from syncr_api.observability import churn
from syncr_api.observability.churn import acceptance_ratio, overridden_count
from syncr_api.observability.product_runner import publish
from syncr_api.observability.readings import ProductReading
from syncr_api.plans.edits import EditedBlock
from syncr_common.metrics import REGISTRY
from syncr_domain.identity import BindingRef, Origin, TransitLeg, is_placed_by_the_solver
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek
from tests.test_alert_rules import deployments

if TYPE_CHECKING:
    from syncr_api.observability.readings import PlacementsById
    from syncr_domain.identifiers import TenantId

ACCEPTANCE = "syncr_proposal_acceptance_ratio"
REPINS = "syncr_repins_per_week"

WEEK = IsoWeek.parse("2026-W07")
A_DATE = date(2026, 2, 9)
PERIOD_START = datetime(2026, 2, 2, tzinfo=UTC)
PERIOD = Interval(PERIOD_START, PERIOD_START + timedelta(weeks=4))
MEASUREMENT_WEEKS = 4

# An hour, and the same hour a day later. Two placements of one block id is one changed block.
PLACED = Interval(PERIOD_START, PERIOD_START + timedelta(hours=1))
MOVED = Interval(PERIOD_START + timedelta(days=1), PERIOD_START + timedelta(days=1, hours=1))

# The two readings of the same seven origins, written out rather than derived, so the parametrised
# cases below cross a literal list against the mapping `overridden_count` reads.
SOLVER_PLACED: Final = (Origin.HABIT, Origin.TASK)
SOURCE_PLACED: Final = (
    Origin.FRAME,
    Origin.TEMPLATE_ENTRY,
    Origin.ANCHOR,
    Origin.PREP,
    Origin.TRANSIT,
)


def a_binding(origin: Origin) -> BindingRef:
    """One content identity of each origin, built through the constructor that spells its key."""
    entity = uuid4()
    match origin:
        case Origin.FRAME:
            return BindingRef.for_routine(entity, on=A_DATE)
        case Origin.TEMPLATE_ENTRY:
            return BindingRef.for_template_entry(entity, on=A_DATE)
        case Origin.HABIT:
            return BindingRef.for_habit(entity, index=0)
        case Origin.TASK:
            return BindingRef.for_task(entity)
        case Origin.ANCHOR:
            return BindingRef.for_anchor(entity)
        case Origin.PREP:
            return BindingRef.for_anchor_prep(entity)
        case Origin.TRANSIT:
            return BindingRef.for_anchor_transit(entity, leg=TransitLeg.OUT)
        case _:  # pragma: no cover - unreachable while Origin has seven members
            assert_never(origin)


def an_edit(origin: Origin) -> EditedBlock:
    """One pin as the churn read projects it: which block, which week, and when."""
    return EditedBlock(iso_week=WEEK, binding=a_binding(origin), created_at=PERIOD_START)


def a_reading(*, accepted_changes: int, edits: tuple[EditedBlock, ...]) -> ProductReading:
    """A reading whose acceptance halves are the two arguments and whose other figures are empty."""
    live: PlacementsById = {f"block-{index}": PLACED for index in range(accepted_changes)}
    candidate: PlacementsById = dict.fromkeys(live, MOVED)
    return ProductReading(
        period=PERIOD,
        measurement_weeks=MEASUREMENT_WEEKS,
        estimates=(),
        verdict_history_by_week={},
        approved_diffs=((live, candidate),) if accepted_changes else (),
        edits=edits,
        weeks_newest_first=(),
    )


def published(family: str, tenant: TenantId) -> float | None:
    return REGISTRY.get_sample_value(family, {"tenant": str(tenant)})


def panel_description() -> str:
    """The Proposal acceptance panel's description, whitespace collapsed so a reflow is safe."""
    parsed = json.loads(
        (deployments() / "grafana" / "dashboards" / "product.json").read_text(encoding="utf-8")
    )
    found = [
        panel["description"]
        for panel in parsed["panels"]
        if panel["title"] == "Proposal acceptance"
    ]
    assert len(found) == 1, "one panel draws this figure, and its title is how this test finds it"
    return " ".join(found[0].split())


def collapsed(text: str) -> str:
    return " ".join(text.split())


class TestWhichEditsReachTheOverriddenHalf:
    """The count, per origin. A pin is a rejected proposal only where there was one to reject."""

    @pytest.mark.parametrize("origin", SOURCE_PLACED)
    def test_an_edit_on_a_block_its_source_placed_is_in_neither_half(self, origin: Origin) -> None:
        assert overridden_count([origin]) == 0

    @pytest.mark.parametrize("origin", SOLVER_PLACED)
    def test_an_edit_on_a_block_the_solve_placed_is_overridden(self, origin: Origin) -> None:
        assert overridden_count([origin]) == 1

    def test_the_two_sets_are_the_whole_vocabulary_and_do_not_overlap(self) -> None:
        """An eighth origin reddens here rather than being silently excluded from both halves."""
        assert set(SOLVER_PLACED) | set(SOURCE_PLACED) == set(Origin)
        assert not set(SOLVER_PLACED) & set(SOURCE_PLACED)

    def test_each_case_above_drives_the_origin_it_names(self) -> None:
        """The control. Every assertion above is worthless if the builder ignores its argument."""
        assert {a_binding(origin).origin for origin in Origin} == set(Origin)


class TestTheRatioOverACorpusHoldingAllThreeClasses:
    """One corpus, three classes of edit, and the figure both readings of it produce."""

    def test_the_narrowed_and_the_wider_reading_of_one_corpus(self) -> None:
        """Two accepted changes; three pins, one of which answered no proposal.

        0.5 rather than 0.4, and the difference is the anchor the user dragged: the solve never
        chose that time, so nothing was rejected by moving it.
        """
        corpus = (an_edit(Origin.ANCHOR), an_edit(Origin.HABIT), an_edit(Origin.TASK))

        narrowed = overridden_count(edit.binding.origin for edit in corpus)

        assert narrowed == 2
        assert acceptance_ratio(accepted=2, overridden=narrowed) == 0.5
        assert acceptance_ratio(accepted=2, overridden=len(corpus)) == 0.4

    def test_a_corpus_of_nothing_but_source_placed_pins_resolves_nothing(self) -> None:
        """Not zero, which is the worst reading a panel can show, and no proposal earned it."""
        corpus = tuple(an_edit(origin) for origin in SOURCE_PLACED)

        narrowed = overridden_count(edit.binding.origin for edit in corpus)

        assert narrowed == 0
        assert acceptance_ratio(accepted=0, overridden=narrowed) is None
        assert acceptance_ratio(accepted=0, overridden=len(corpus)) == 0.0


class TestTheGaugeThePanelDraws:
    """The whole path: a reading in, a sample out. The count alone could be wired to nothing."""

    def test_the_published_figure_counts_only_the_edits_that_displaced_a_placement(self) -> None:
        tenant = uuid4()
        corpus = (an_edit(Origin.ANCHOR), an_edit(Origin.ANCHOR), an_edit(Origin.HABIT))

        publish(tenant, a_reading(accepted_changes=2, edits=corpus))

        assert published(ACCEPTANCE, tenant) == pytest.approx(2 / 3)

    def test_a_period_of_source_placed_pins_alone_leaves_the_gauge_unset(self) -> None:
        """Absent rather than zero, and the re-pin gauge is what shows the publication ran."""
        tenant = uuid4()
        corpus = tuple(an_edit(origin) for origin in SOURCE_PLACED)

        publish(tenant, a_reading(accepted_changes=0, edits=corpus))

        assert published(ACCEPTANCE, tenant) is None
        assert published(REPINS, tenant) == 0.0

    def test_every_pin_still_reaches_the_re_pin_count(self) -> None:
        """The narrowing is the acceptance ratio's alone: a re-pin is a correction of any block."""
        tenant = uuid4()
        anchor = an_edit(Origin.ANCHOR)

        publish(tenant, a_reading(accepted_changes=1, edits=(anchor, anchor)))

        assert published(REPINS, tenant) == 1 / MEASUREMENT_WEEKS


class TestThePanelSaysWhatTheDenominatorCounts:
    """An operator reads the panel rather than the module, so it carries the same two claims."""

    def test_it_names_every_origin_the_count_excludes(self) -> None:
        """Keyed to the mapping rather than to a list, so a widened vocabulary reddens here."""
        description = panel_description()

        for origin in Origin:
            if not is_placed_by_the_solver(origin):
                assert origin.value in description

    def test_it_names_the_two_origins_the_count_keeps(self) -> None:
        description = panel_description()

        for origin in Origin:
            if is_placed_by_the_solver(origin):
                assert origin.value in description

    def test_it_records_the_case_still_counted_that_a_widened_read_would_exclude(self) -> None:
        description = panel_description()

        assert "a pin in a week the solver never touched" in description
        assert "no proposal behind it" in description

    def test_the_module_records_the_same_residual_in_the_same_words(self) -> None:
        """Two places state it, so the crossing is what stops one of them drifting."""
        assert churn.__doc__ is not None
        recorded = collapsed(churn.__doc__)

        assert "a pin in a week the solver never touched" in recorded
        assert "no proposal behind it" in recorded

    @pytest.mark.parametrize(
        ("pattern", "sample"),
        [
            (r"[Tt]icket \d+", "ticket 1540 carries the narrowing"),
            (r"US-[A-Z]+-\d+", "US-OPS-06 asked for this"),
            (r"section \d+", "stated in section 11"),
        ],
    )
    def test_neither_the_panel_nor_the_module_cites_a_planning_artifact(
        self, pattern: str, sample: str
    ) -> None:
        """Each pattern matches its own shape first: one that matched nothing is not a guard."""
        cite = re.compile(pattern)

        assert cite.search(sample) is not None
        assert cite.search(panel_description()) is None
        assert churn.__doc__ is not None
        assert cite.search(churn.__doc__) is None
