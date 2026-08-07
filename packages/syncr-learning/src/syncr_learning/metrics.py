"""The six metric families the nightly run exports, on the registry ``syncr-common`` owns.

The job has no HTTP surface, so nothing serves an exposition here: a one-shot container is not
scrapeable, and the run instead writes its figures to the registry and the entrypoint pushes or logs
them. What matters for this module is that the families exist and are named exactly as section 18
and
ticket 54's dashboards spell them, because an alert reads a name.

``syncr_learning_samples`` is labelled by PARAMETER, which is the label section 11's own maturity
table is keyed on: an alert about a gate is an alert about one parameter, and one series per
parameter is what lets a dashboard draw six progress bars. The label set is bounded by
:data:`~syncr_learning.config.FITTED_PARAMETERS`, so it cannot grow with the data.

``syncr_weight_set_version`` is a GAUGE rather than a counter. A revert lowers it, which a counter
cannot express, and the point of the series is "which artefact is in force" rather than "how many
have ever been written".
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from syncr_common.metrics import REGISTRY

RUN_DURATION = Histogram(
    "syncr_learning_run_duration_seconds",
    "Wall time of one nightly learning run, from the first read to the last write.",
    registry=REGISTRY,
)

PARAMETERS_READY = Gauge(
    "syncr_learning_parameters_ready",
    "Parameters at or above their maturity threshold, so applied by the solver.",
    labelnames=("tenant",),
    registry=REGISTRY,
)

PARAMETERS_COLLECTING = Gauge(
    "syncr_learning_parameters_collecting",
    "Parameters below their maturity threshold, so not applied at all.",
    labelnames=("tenant",),
    registry=REGISTRY,
)

SAMPLES = Gauge(
    "syncr_learning_samples",
    "Observations behind each parameter, by the parameter they are counted for.",
    labelnames=("tenant", "parameter"),
    registry=REGISTRY,
)

FITS_REJECTED = Counter(
    "syncr_learning_fit_rejected_total",
    "Fits refused rather than applied, by the parameter refused and the reason it was.",
    labelnames=("parameter", "reason"),
    registry=REGISTRY,
)

WEIGHT_SET_VERSION = Gauge(
    "syncr_weight_set_version",
    "The weight-set version in force for this tenant. Falls on a revert, hence a gauge.",
    labelnames=("tenant",),
    registry=REGISTRY,
)

UNMEASURED_EDITS = Gauge(
    "syncr_learning_edits_without_measurement",
    "Edit events excluded from the weight fit for carrying no measured term difference.",
    labelnames=("tenant",),
    registry=REGISTRY,
)
"""The corpus that predates the measurement, counted rather than silently skipped.

E5 forbids pruning these rows, so the figure only ever falls as the corpus grows. Exported because
without it a weight gate held back by history is indistinguishable from one held back by a quiet
user.
"""
