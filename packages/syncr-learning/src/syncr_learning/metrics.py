"""The metric families the nightly run exports, on the registry ``syncr-common`` owns.

The job has no HTTP surface, so nothing serves an exposition here: a one-shot container is not
scrapeable, and the run instead writes its figures to the registry and the entrypoint pushes or logs
them. What matters for this module is that a family's NAME is a contract with whatever reads it:
``LearningJobFailed`` in ``deployments/prometheus/alerts.yml`` reads
``syncr_learning_run_duration_seconds`` by name, so a rename here is a rename there.

``syncr_learning_samples`` is labelled by PARAMETER: an alert about a gate is an alert about one
parameter, and one series per parameter is what lets a dashboard draw one progress bar each. The
label set is bounded by :data:`~syncr_learning.config.FITTED_PARAMETERS`, so it cannot grow with the
data.

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
    "Parameters not applied after a run, by the parameter and why it was not.",
    labelnames=("parameter", "reason"),
    registry=REGISTRY,
)
"""Counts a parameter the run did NOT apply, which is wider than a fit that was refused.

The ``reason`` label separates the two: ``below_threshold`` is a young corpus, which is the ordinary
case and not a fault, and ``refused`` is a fit the arithmetic would not stand behind. An alert on
this family has to read the label, because the name alone would suggest every collecting parameter
is a failure and a new tenant would look like a broken one.
"""

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

Nothing prunes these rows, so the figure only ever falls as the corpus grows. Exported because
without it a weight gate held back by history is indistinguishable from one held back by a quiet
user.
"""
