"""The nightly run: idempotence, the exit code, and what the job structurally cannot write.

Driven against in-memory ports, which is what makes the run's own rules decidable without Postgres.
The storage adapter has its own suite against a real database; what is tested here is the run.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from types import FunctionType
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
import structlog

from syncr_common.logging import configure_logging
from syncr_common.metrics import REGISTRY
from syncr_domain.promotion import detect_repeated_pins
from syncr_learning import job as job_module
from syncr_learning.config import OBJECTIVE_WEIGHTS, THRESHOLD_DURATION_MULTIPLIER, THRESHOLDS
from syncr_learning.job import NoWeightsInForce, TenantRun, run, run_for_tenant
from syncr_learning.statements import UNMEASURED_EDITS_ARE_NEITHER_FITTED_NOR_COUNTED
from tests.builders import AREA, TENANT, a_week_of, corpus, edit, outcome, pin
from tests.test_rank import IN_FORCE

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

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


@pytest.fixture
def rendered_log() -> Iterator[io.StringIO]:
    """Every line the run emits, rendered as the container writes it.

    Logging configuration is process-global and nothing else in this suite configures it, so the
    fixture hands back the default rather than leaving a second opinion in place.
    """
    stream = io.StringIO()
    configure_logging(environment="test", log_level="info", stream=stream)
    yield stream
    structlog.reset_defaults()


def lines_of(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def the_line(stream: io.StringIO, event: str) -> dict[str, object]:
    """The one line named ``event``, or a failure naming what was emitted instead.

    Every assertion below about a field the line does NOT carry is stated over this, so a run that
    logged nothing fails here rather than passing an absence nobody produced.
    """
    emitted = lines_of(stream)
    named = [line for line in emitted if line.get("event") == event]
    assert len(named) == 1, (
        f"expected one {event}, emitted {[line.get('event') for line in emitted]}"
    )
    return named[0]


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
        # rather than only in a histogram a one-shot container cannot be scraped for. Bounded rather
        # than non-negative: `>= 0.0` passes on a hardcoded zero, which is the one value that would
        # mean the figure is not being taken at all.
        report = await run(a_reader(), RecordingWriter(), at=AT)

        assert 0.0 < report.seconds < 60.0


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

        ready = REGISTRY.get_sample_value(
            "syncr_learning_parameters_ready", {"tenant": str(TENANT)}
        )
        version = REGISTRY.get_sample_value("syncr_weight_set_version", {"tenant": str(TENANT)})

        assert ready == report.tenants[0].fitted.ready
        assert version == report.tenants[0].version

    async def test_the_corpus_that_predates_the_measurement_reports_both_figures(self) -> None:
        # The reader's own situation, in one run: a gauge counting every row that was left out,
        # beside a row saying none of them counted, and a sentence saying why both are true.
        unmeasured_edits = THRESHOLDS[OBJECTIVE_WEIGHTS] + 10
        reader = a_reader(
            corpora={TENANT: corpus(edits=[edit(difference=None) for _ in range(unmeasured_edits)])}
        )
        writer = RecordingWriter()

        await run(reader, writer, at=AT)
        _, fitted = writer.appended[0]
        row = next(one for one in fitted.maturity if one.parameter == OBJECTIVE_WEIGHTS)

        left_out = REGISTRY.get_sample_value(
            "syncr_learning_edits_without_measurement", {"tenant": str(TENANT)}
        )

        assert left_out == unmeasured_edits
        assert (row.samples, row.threshold) == (0, THRESHOLDS[OBJECTIVE_WEIGHTS])
        assert UNMEASURED_EDITS_ARE_NEITHER_FITTED_NOR_COUNTED in row.plain_language

    async def test_the_repeated_pins_this_run_reads_produce_no_figure_of_their_own(
        self, rendered_log: io.StringIO
    ) -> None:
        # The corpus a promotion IS raised from, so the absence below is measured over an input that
        # could produce a candidate rather than over an empty pin list. The api derives its own
        # candidates at read time from its own pin rows; this run reports none.
        from syncr_domain.weeks import IsoWeek

        pins = [pin(iso_week=IsoWeek(year=2026, week=number), hour=13) for number in (7, 8, 9)]
        reader = a_reader(corpora={TENANT: corpus(pins=pins)})

        report = await run(reader, RecordingWriter(), at=AT)

        line = the_line(rendered_log, "learning.tenant.fitted")

        assert len(detect_repeated_pins(pins)) == 1, "the fixture must be detectable"
        assert len(report.tenants) == 1
        assert [one.name for one in fields(TenantRun)] == ["tenant_id", "version", "fitted"]
        assert [key for key in line if "candidate" in key or "promotion" in key] == []

    async def test_the_fitted_line_carries_this_tenant_s_figures_and_nothing_else(
        self, rendered_log: io.StringIO
    ) -> None:
        # An exact key set rather than a membership test: a field added to the line a runbook reads
        # is as much a change as a field removed from it, and only one of the two has a home here.
        report = await run(a_reader(), RecordingWriter(), at=AT)

        line = the_line(rendered_log, "learning.tenant.fitted")

        assert set(line) == {
            "event",
            "level",
            "timestamp",
            "service",
            "tenant_id",
            "version",
            "ready",
            "collecting",
            "weight_fit_rejected",
        }
        assert line["tenant_id"] == str(TENANT)
        assert line["version"] == report.tenants[0].version
        assert line["ready"] == report.tenants[0].fitted.ready

    def test_the_module_defines_the_run_and_no_reporter_of_a_candidate(self) -> None:
        # Read off the module rather than trusted, in the shape the port tests above use. The public
        # surface is an equality and the private one a property, so extracting a helper is free and
        # a helper whose only caller could be a log line is not.
        defined = {
            name
            for name, value in vars(job_module).items()
            if isinstance(value, FunctionType) and value.__module__ == job_module.__name__
        }

        assert {name for name in defined if not name.startswith("_")} == {"run", "run_for_tenant"}
        assert [name for name in defined if "candidate" in name or "promotion" in name] == []

    def test_the_module_says_where_a_promotion_candidate_is_derived(self) -> None:
        stated = " ".join((job_module.__doc__ or "").split())

        assert (
            "the api derives repeated-pin promotion candidates at read time from its own pin rows"
            in stated
        )
