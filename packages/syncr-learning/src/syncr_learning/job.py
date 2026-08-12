"""The nightly run: load, extract, fit, gate, append. One pass per tenant, then a verdict.

## What the run does and does not do

It APPENDS a new weight-set version per tenant and never activates one. Activation is a user-facing
act with a re-solve behind it, and a job that activated its own output would move the plan under the
user overnight.

It writes nothing else. There is no path from here to ``plan_revisions``, ``pins`` or
``block_outcomes``: the writer port has one method, so a module here has no call to make.

It detects nothing else either: the api derives repeated-pin promotion candidates at read time from
its own pin rows, so the raise does not wait for a nightly run.

## Idempotence, and where it comes from

Two runs over the same rows produce the same figures. Nothing is carried between runs and every
derivation is pure, so the only input that differs is the instant stamped on the row. What a second
run adds is a version, not a different answer, and :func:`run_for_tenant` returning the artefact is
what lets a test assert the equality directly.

## A refused fit and a failed fit are different outcomes

A refused fit is ordinary: a gate is not met, or the weight vector came back negative, or it ranked
the corpus no better than the incumbent. The run records it, keeps the figure in force and carries
on.

A FAILED fit is an exception, and the run exits non-zero for it. ``LearningJobFailed`` in
``deployments/prometheus/alerts.yml`` reads that exit at severity info, and the previous active
weight set stays in place, which is a benign degradation: the solver keeps working with slightly
older parameters. What the exit code buys is that the failure is visible to the monitoring stack
rather than silently producing no new version.

One tenant's failure does not stop the others. A run over twelve tenants where one has a corrupt row
should write eleven versions and report one failure, because the alternative is one bad row costing
every tenant a night.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_common.logging import get_logger
from syncr_learning import metrics
from syncr_learning.config import OBJECTIVE_TERMS, OBJECTIVE_WEIGHTS
from syncr_learning.features import extract
from syncr_learning.fitting import fit_everything
from syncr_learning.gates import parameter_of
from syncr_learning.preferences import unmeasured

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.identifiers import TenantId
    from syncr_learning.fitting import FittedParameters
    from syncr_learning.ports import CorpusReader, ParameterWriter

_log = get_logger("syncr.learning")


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantRun:
    """What one tenant's pass produced."""

    tenant_id: TenantId
    version: int
    fitted: FittedParameters


@dataclass(frozen=True, slots=True, kw_only=True)
class RunReport:
    """What the whole run produced, and what failed. The entrypoint's exit code reads this.

    ``failures`` holds one line per tenant whose pass raised, naming the tenant and the error. A
    report with any failure is a non-zero exit, which is what makes a partly-successful night
    visible rather than reported as a success with fewer rows than yesterday.
    """

    tenants: tuple[TenantRun, ...]
    failures: tuple[str, ...]
    seconds: float

    @property
    def failed(self) -> bool:
        """Whether any tenant's pass raised, which is what the container's exit code is."""
        return bool(self.failures)


async def run(reader: CorpusReader, writer: ParameterWriter, *, at: datetime) -> RunReport:
    """One nightly pass over every tenant. Answers with what was written and what failed."""
    started = time.perf_counter()
    completed: list[TenantRun] = []
    failures: list[str] = []
    for tenant_id in await reader.tenants():
        try:
            completed.append(await run_for_tenant(reader, writer, tenant_id=tenant_id, at=at))
        except Exception as error:  # noqa: BLE001 - see below
            # Caught per tenant and re-reported rather than propagated: one corrupt row must not
            # cost every other tenant a night, and the exit code still carries the failure out.
            # Blind because a corpus can fail in any layer -- a driver error, a value the domain
            # refuses, an optimiser that will not converge -- and the run's answer is the same for
            # every one of them: name the tenant, keep going, exit non-zero.
            failures.append(f"{tenant_id}: {type(error).__name__}: {error}")
            _log.exception("learning.tenant.failed", tenant_id=str(tenant_id))
    seconds = time.perf_counter() - started
    metrics.RUN_DURATION.observe(seconds)
    _log.info(
        "learning.run.finished",
        tenants=len(completed),
        failures=len(failures),
        seconds=round(seconds, 3),
    )
    return RunReport(tenants=tuple(completed), failures=tuple(failures), seconds=seconds)


async def run_for_tenant(
    reader: CorpusReader,
    writer: ParameterWriter,
    *,
    tenant_id: TenantId,
    at: datetime,
) -> TenantRun:
    """One tenant's pass: read, fit, and append one version.

    Refuses a tenant with no active weight set rather than inventing an incumbent. Every scalar's
    fallback and the weight fit's own comparison are stated against the figures in force, so without
    them the run has nothing to fall back TO and nothing to beat.
    """
    in_force = await reader.weights_in_force(tenant_id)
    if in_force is None:
        raise NoWeightsInForce(
            f"tenant {tenant_id} has no active weight set, so a fit could neither fall back to the "
            "figures in force nor be compared against them. Provisioning seeds version 1 in the "
            "transaction that creates a tenant"
        )
    corpus = await reader.corpus(tenant_id)
    observations = extract(corpus)
    fitted = fit_everything(
        observations,
        in_force={term: in_force[term] for term in OBJECTIVE_TERMS},
        switch_cost_in_force=in_force["context_switch_cost"],
        churn_tolerance_in_force=in_force["churn_tolerance"],
        area_names=await reader.area_names(tenant_id),
        at=at,
    )
    version = await writer.append_version(tenant_id, fitted.artifact)
    _record(
        tenant_id,
        fitted,
        version=version,
        unmeasured_edits=unmeasured(corpus.edits, corpus.off_plan),
    )
    _log.info(
        "learning.tenant.fitted",
        tenant_id=str(tenant_id),
        version=version,
        ready=fitted.ready,
        collecting=fitted.collecting,
        weight_fit_rejected=fitted.rank.rejection,
    )
    return TenantRun(tenant_id=tenant_id, version=version, fitted=fitted)


class NoWeightsInForce(Exception):
    """A tenant has no active weight set, so nothing could be fitted against one."""


def _record(
    tenant_id: TenantId,
    fitted: FittedParameters,
    *,
    version: int,
    unmeasured_edits: int,
) -> None:
    """Every gauge this tenant's pass reports, and the counter a refusal increments."""
    tenant = str(tenant_id)
    metrics.PARAMETERS_READY.labels(tenant=tenant).set(fitted.ready)
    metrics.PARAMETERS_COLLECTING.labels(tenant=tenant).set(fitted.collecting)
    metrics.WEIGHT_SET_VERSION.labels(tenant=tenant).set(version)
    metrics.UNMEASURED_EDITS.labels(tenant=tenant).set(unmeasured_edits)
    for parameter, samples in fitted.samples_by_parameter().items():
        metrics.SAMPLES.labels(tenant=tenant, parameter=parameter).set(samples)
    for row in fitted.artifact.maturity:
        if row.value is None:
            metrics.FITS_REJECTED.labels(
                parameter=parameter_of(row), reason=_reason_for(row.parameter, fitted)
            ).inc()


def _reason_for(parameter: str, fitted: FittedParameters) -> str:
    """A bounded reason label. Two values, because free text would be unbounded cardinality.

    The weight fit's own refusal message is logged in full and is not a label: a message quoting a
    sample count would make one series per corpus size.
    """
    if parameter == OBJECTIVE_WEIGHTS and fitted.rank.rejection is not None:
        return "refused"
    return "below_threshold"
