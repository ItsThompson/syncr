"""Every figure the backup path is stated with, in one place, because two of them are alerts.

A runbook is read once, under pressure. A figure quoted in one that has drifted from the deployment
is worse than no figure, so ``BACKUP_STALE_AFTER`` and ``WAL_STALE_AFTER`` are the SAME constants
the ``BackupStale`` expression is written from and the runbooks are crossed against
(``packages/syncr-api/tests/test_deployment_figures.py``).

The two objectives are the promise the whole path exists to keep, and each one is enforced rather
than asserted: the drill fails when it takes longer than ``RECOVERY_TIME_OBJECTIVE``, and
``RECOVERY_POINT_OBJECTIVE`` is what ``ARCHIVE_TIMEOUT`` plus ``SHIP_INTERVAL`` has to fit inside.
"""

from __future__ import annotations

from typing import Final

# --- The schedule -----------------------------------------------------------

# Host time. The learning one-shot runs at the same hour, which is why the engine turns on
# `pool_pre_ping`: a connection severed by a Postgres restart must be discarded rather than failing
# a tenant's night.
NIGHTLY_HOUR: Final = 3

# How often WAL segments are shipped off-host, and how long Postgres waits before forcing a segment
# switch on a quiet database. Together they bound the recovery point: the newest committed
# transaction can sit unshipped for at most one archive timeout plus one ship interval.
SHIP_INTERVAL_SECONDS: Final = 60
ARCHIVE_TIMEOUT_SECONDS: Final = 120

# --- The two objectives -----------------------------------------------------

RECOVERY_POINT_OBJECTIVE_SECONDS: Final = 5 * 60
RECOVERY_TIME_OBJECTIVE_SECONDS: Final = 60 * 60

# --- The two staleness thresholds `BackupStale` is written from --------------

# 36 hours: one nightly run plus most of a day of grace.
BACKUP_STALE_AFTER_SECONDS: Final = 36 * 60 * 60

# Fifteen minutes, against a recovery point of five. The gap is deliberate and the runbook says so:
# the objective is breached from the moment the series stops moving, not from when the alert fires,
# and an alert that fired on one refused upload would be an alert the operator learns to ignore.
WAL_STALE_AFTER_SECONDS: Final = 15 * 60

# --- Retention --------------------------------------------------------------

DAILY_COPIES: Final = 7
WEEKLY_COPIES: Final = 4
MONTHLY_COPIES: Final = 6

# Which dump is a weekly one, and which a monthly one. Monday because the product's own unit is the
# ISO week and the weekly session sits at that boundary, so the weekly copy is the one taken with
# the week's plan freshly adopted. Monday is 0, as `date.weekday()` numbers it.
WEEKLY_ON_WEEKDAY: Final = 0
MONTHLY_ON_DAY: Final = 1

# WAL is kept as far back as the oldest dump it could be replayed onto, plus a day: a dump with no
# WAL after it can only be restored to the instant it was taken, which is the recovery point this
# path exists to improve on.
WAL_RETENTION_MARGIN_SECONDS: Final = 24 * 60 * 60

# --- Where things are, inside the ops container ------------------------------

# The dump is written here first and uploaded from here. A named volume, not the database's own: a
# backup on the same disk as the database is not a backup, and this staging copy is not the backup.
STAGING_DIR: Final = "/var/backups/syncr"

# What the drill downloads into. Separate from the staging directory so a drill cannot be satisfied
# by a file the dump step left behind.
SCRATCH_DIR: Final = "/var/backups/restore"

# Postgres writes archived segments here through its `archive_command`, and the shipper drains it.
WAL_STAGING_DIR: Final = "/wal-archive"

# The node exporter's textfile collector. Shared as a named volume with the exporter and with the
# nightly learning one-shot, because a process that has exited cannot be scraped.
TEXTFILE_DIR: Final = "/var/lib/node_exporter/textfile"

# --- Object layout in the bucket ---------------------------------------------

DUMP_PREFIX: Final = "dumps"
WAL_PREFIX: Final = "wal"

# --- The two families written into the textfile collector --------------------
#
# Both are read by `BackupStale`, which is the only alert in this deployment about data that cannot
# be recovered. Neither is in the Prometheus registry: they are declared as externally produced in
# `packages/syncr-api/tests/metric_declarations.py`, with this package named as the producer.

BACKUP_METRIC: Final = "syncr_backup_last_success_timestamp_seconds"
WAL_METRIC: Final = "syncr_wal_archive_last_success_timestamp_seconds"

# --- The manifest -----------------------------------------------------------

# The fingerprint the api image writes before the dump is taken: per-table row counts, every
# rotation habit's derived cursor, and the migration head. The drill's pass condition is stated over
# this file
# rather than over an exit code, because a dump that restores without error and comes back empty is
# the failure this whole ticket exists to prevent.
MANIFEST_SUFFIX: Final = ".manifest.json"
DUMP_SUFFIX: Final = ".dump"
ENCRYPTED_SUFFIX: Final = ".gpg"

# How stale a fingerprint may be when the dump step picks it up. Long enough for a slow read on a
# loaded host, short enough that yesterday's file cannot be uploaded beside today's dump.
MANIFEST_MAX_AGE_SECONDS: Final = 30 * 60

# The tables whose rows the restore drill is stated over, schema-qualified as `pg_restore --list`
# prints them and as the fingerprint's own keys spell them.
#
# A DRILL OVER AN EMPTY TABLE PROVES NOTHING: an empty table restores perfectly, so the verdict
# refuses rather than reporting a pass. These five are the ones the ticket names as the evidence,
# and `packages/syncr-api/tests/test_deployment_figures.py` crosses them against the table-name
# constants
# the application declares, so a rename fails a gate instead of quietly making a check unreachable.
EVIDENCE_TABLES: Final = (
    "public.plan_revisions",
    "public.block_outcomes",
    "public.pins",
    "public.week_adjustments",
    "public.edit_events",
)
