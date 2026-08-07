"""The nightly run: idempotence, the exit code, and what the job structurally cannot write.

Driven against in-memory ports, which is what makes the run's own rules decidable without Postgres.
The storage adapter has its own suite against a real database; what is tested here is the run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from syncr_learning.config import THRESHOLD_DURATION_MULTIPLIER
from syncr_learning.job import NoWeightsInForce, promotion_candidates, run, run_for_tenant
from syncr_learning.metrics import PARAMETERS_READY, WEIGHT_SET_VERSION
from tests.builders import AREA, TENANT, a_week_of, corpus, outcome, pin
from tests.test_rank import IN_FORCE

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.identifiers import TenantId
    from syncr_learning.artifact import FittedWeightSet
    from syncr_learning.facts import TenantCorpus

AT = datetime(2026, 2, 16, 3, 0, tzinfo=UTC)
NEXT_NIGHT = datetime(2026, 2, 17, 3, 0, tzinfo=UTC)

IN_FORCE_WITH_SCALARS = {**IN_FORCE, "context_switch_cost": 1.0, "churn_tolerance": 3.0}


@dataclass
class InMemoryReader:
    """The corpus reader, over values. Four reads and nothing that could write."""

    corpora: dict[TenantId, TenantCorpus]
    weights: Mapping[str, float] | None = field(default=None)
    names: Mapping[str, str] = field(default_factory=lambda: {str(AREA): "Fitness"})
    fail_for: TenantId | None = None

    async def tenants(self) -> Sequence[TenantId]:
        return sorted(self.corpora)

    async def corpus(self, tenant_id: TenantId) -> TenantCorpus:
        if tenant_id == self.fail_for:
            raise RuntimeError("a stored row could not be rebuilt")
        return self.corpora[tenant_id]

    async def weights_in_force(self, tenant_id: TenantId) -> Mapping[str, float] | None:
        return self.weights

    async def area_names(self, tenant_id: TenantId) -> Mapping[str, str]:
        return self.names


@dataclass
class RecordingWriter:
    """The parameter writer. Records what was appended, in order, and holds no other write."""

    appended: list[tuple[TenantId, FittedWeightSet]] = field(default_factory=list)

    async def append_version(self, tenant_id: TenantId, fitted: FittedWeightSet) -> int:
        self.appended.append((tenant_id, fitted))
        return len(self.appended) + 1


def a_reader(**overrides: object) -> InMemoryReader:
    defaults: dict[str, object] = {
        "corpora": {TENANT: a_week_of(THRESHOLD_DURATION_MULTIPLIER)},
        "weights": IN_FORCE_WITH_SCALARS,
    }
    return InMemoryReader(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestTheRunAppendsAndNeverActivates:
    async def test_one_pass_appends_one_version_per_tenant(self) -> None:
        second = uuid4()
        reader = a_reader(
            corpora={TENANT: a_week_of(20), second: a_week_of(20)},
        )
        writer = RecordingWriter()

        report = await run(reader, writer, at=AT)

        assert len(writer.appended) == 2
        assert len(report.tenants) == 2
        assert report.failed is False

    def test_the_writer_port_has_no_activation_and_no_update(self) -> None:
        # A nightly job that activated its own output would move the plan under the user overnight,
        # so there is no method to call. Read off the protocol rather than trusted.
        from syncr_learning.ports import ParameterWriter

        methods = {name for name in dir(ParameterWriter) if not name.startswith("_")}

        assert methods == {"append_version"}

    def test_the_reader_port_holds_no_write_at_all(self) -> None:
        from syncr_learning.ports import CorpusReader

        methods = {name for name in dir(CorpusReader) if not name.startswith("_")}

        assert methods == {"tenants", "corpus", "weights_in_force", "area_names"}

    async def test_the_artefact_states_it_was_fitted_and_when(self) -> None:
        writer = RecordingWriter()
        await run(a_reader(), writer, at=AT)

        _, fitted = writer.appended[0]

        assert fitted.columns()["origin"] == "fitted"
        assert fitted.columns()["fitted_at"] == AT


class TestIdempotence:
    async def test_two_runs_over_the_same_rows_produce_the_same_figures(self) -> None:
        reader = a_reader(corpora={TENANT: a_week_of(20)})
        writer = RecordingWriter()

        await run(reader, writer, at=AT)
        await run(reader, writer, at=NEXT_NIGHT)

        first, second = (fitted for _, fitted in writer.appended)

        assert first.duration_multiplier == second.duration_multiplier
        assert first.time_of_day_fitness == second.time_of_day_fitness
        assert first.skip_probability == second.skip_probability
        assert first.context_switch_cost == second.context_switch_cost
        assert first.churn_tolerance == second.churn_tolerance
        assert first.term_weights == second.term_weights

    async def test_the_maturity_rows_are_identical_and_in_the_same_order(self) -> None:
        # Row ORDER matters: it is what the screen renders, so two runs that produced the same
        # figures in a different order would redraw the table for no reason.
        reader = a_reader(corpora={TENANT: a_week_of(20)})
        writer = RecordingWriter()

        await run(reader, writer, at=AT)
        await run(reader, writer, at=NEXT_NIGHT)

        first, second = (fitted for _, fitted in writer.appended)

        assert [row.parameter for row in first.maturity] == [
            row.parameter for row in second.maturity
        ]
        assert [row.value for row in first.maturity] == [row.value for row in second.maturity]

    async def test_only_the_stamped_instant_differs_between_two_runs(self) -> None:
        reader = a_reader(corpora={TENANT: a_week_of(20)})
        writer = RecordingWriter()

        await run(reader, writer, at=AT)
        await run(reader, writer, at=NEXT_NIGHT)

        first, second = (fitted.columns() for _, fitted in writer.appended)
        differing = {key for key in first if first[key] != second[key]}

        assert differing == {"fitted_at"}

    async def test_a_corrected_confirmation_changes_the_next_run_and_not_the_last_one(self) -> None:
        # The refit rule, at the run: the previous version's row is untouched and the new one
        # carries the corrected figure, because a run reads the log from scratch.
        original = a_week_of(20, actual_minutes=82)
        reader = a_reader(corpora={TENANT: original})
        writer = RecordingWriter()
        await run(reader, writer, at=AT)

        reader.corpora[TENANT] = corpus(
            revisions=original.revisions,
            outcomes=[
                outcome(index=index, actual_minutes=45, state=original.outcomes[index].state)
                for index in range(20)
            ],
        )
        await run(reader, writer, at=NEXT_NIGHT)

        first, second = (fitted for _, fitted in writer.appended)

        assert first.duration_multiplier[str(AREA)] > second.duration_multiplier[str(AREA)]


class TestTheExitCode:
    async def test_a_tenant_whose_pass_raises_is_reported_as_a_failure(self) -> None:
        reader = a_reader(corpora={TENANT: a_week_of(20)}, fail_for=TENANT)
        writer = RecordingWriter()

        report = await run(reader, writer, at=AT)

        assert report.failed is True
        assert len(report.failures) == 1
        assert str(TENANT) in report.failures[0]
        assert writer.appended == []

    async def test_one_tenant_s_failure_does_not_cost_the_others_their_night(self) -> None:
        broken = UUID(int=1)
        healthy = UUID(int=2)
        reader = a_reader(corpora={broken: a_week_of(20), healthy: a_week_of(20)}, fail_for=broken)
        writer = RecordingWriter()

        report = await run(reader, writer, at=AT)

        assert len(writer.appended) == 1
        assert writer.appended[0][0] == healthy
        assert report.failed is True

    async def test_a_clean_run_reports_no_failure(self) -> None:
        report = await run(a_reader(), RecordingWriter(), at=AT)

        assert report.failed is False
        assert report.failures == ()

    async def test_a_tenant_with_no_active_weight_set_is_refused_rather_than_guessed_at(
        self,
    ) -> None:
        # Every scalar's fallback and the weight comparison are stated against the figures in force,
        # so without them the run has nothing to fall back to and nothing to beat.
        reader = a_reader(weights=None)

        with pytest.raises(NoWeightsInForce, match="no active weight set"):
            await run_for_tenant(reader, RecordingWriter(), tenant_id=TENANT, at=AT)

    async def test_the_run_reports_the_wall_time_it_took(self) -> None:
        # The five-minute budget is measured against this figure, so it has to exist on the report
        # rather than only in a histogram the container cannot be scraped for.
        report = await run(a_reader(), RecordingWriter(), at=AT)

        assert report.seconds >= 0.0


class TestARefusedFitIsNotAFailedRun:
    async def test_a_corpus_below_every_gate_still_appends_a_version(self) -> None:
        # A young corpus is the ordinary case, not an error: the run writes a version whose figures
        # are the ones in force and whose maturity rows say what is still collecting.
        reader = a_reader(corpora={TENANT: a_week_of(2)})
        writer = RecordingWriter()

        report = await run(reader, writer, at=AT)

        assert report.failed is False
        assert len(writer.appended) == 1
        _, fitted = writer.appended[0]
        assert fitted.duration_multiplier == {}
        assert fitted.term_weights == IN_FORCE

    async def test_a_refused_weight_fit_leaves_the_seven_weights_as_they_were(self) -> None:
        reader = a_reader(corpora={TENANT: a_week_of(20)})
        writer = RecordingWriter()

        report = await run(reader, writer, at=AT)
        _, fitted = writer.appended[0]

        assert report.tenants[0].fitted.rank.weights is None
        assert fitted.term_weights == IN_FORCE


class TestWhatTheRunReports:
    async def test_the_gauges_carry_this_tenant_s_figures(self) -> None:
        reader = a_reader(corpora={TENANT: a_week_of(THRESHOLD_DURATION_MULTIPLIER)})
        writer = RecordingWriter()

        report = await run(reader, writer, at=AT)

        ready = PARAMETERS_READY.labels(tenant=str(TENANT))._value.get()
        version = WEIGHT_SET_VERSION.labels(tenant=str(TENANT))._value.get()

        assert ready == report.tenants[0].fitted.ready
        assert version == report.tenants[0].version

    async def test_the_repeated_pins_are_returned_rather_than_written(self) -> None:
        from syncr_domain.weeks import IsoWeek

        pins = [pin(iso_week=IsoWeek(year=2026, week=number), hour=13) for number in (7, 8, 9)]
        reader = a_reader(corpora={TENANT: corpus(pins=pins)})

        report = await run(reader, RecordingWriter(), at=AT)

        assert len(promotion_candidates(report)) == 1
        assert promotion_candidates(report)[0].local_time == "13:00"
