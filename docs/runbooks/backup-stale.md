# No successful backup in 36 hours, or no WAL archived in 15 minutes

## Trigger

`BackupStale` fires. It is **critical**, and it is the only alert in this deployment about data that
cannot be recovered.

```
absent(syncr_backup_last_success_timestamp_seconds)
or time() - max(syncr_backup_last_success_timestamp_seconds) > 129600
or absent(syncr_wal_archive_last_success_timestamp_seconds)
or time() - max(syncr_wal_archive_last_success_timestamp_seconds) > 900
```

129600 seconds is **36 hours**, one nightly run plus most of a day of grace. 900 is **15 minutes**. It
waits **10 minutes**.

## Which half fired

**Read this before anything else**, because the two halves mean very different amounts of exposure:

```
time() - max(syncr_backup_last_success_timestamp_seconds)          # seconds since the last dump
time() - max(syncr_wal_archive_last_success_timestamp_seconds)     # seconds since WAL was last shipped
```

| Fresh | Stale | Exposure |
|---|---|---|
| dump | WAL | Everything up to the last 03:00 is recoverable. Anything since is at risk |
| WAL | dump | The recovery point is still minutes old. A recovery needs the older dump plus more WAL to replay |
| neither | | Nothing since the last successful copy is recoverable. This is the case to treat as an incident |

## Why the WAL half is 15 minutes against an objective of 5

The recovery point objective is **under five minutes**, and it is bounded by two figures:
`archive_timeout` at 120 seconds, which is how long Postgres waits before forcing a segment switch on a
quiet database, plus the shipper's 60-second interval. Worst case, three minutes.

The alert threshold is fifteen. **The objective is breached from the moment the series stops moving, not
from when this fires**: the gap exists so one refused upload on a flaky network is not a page, because
an alert that pages on a transient is an alert the operator learns to ignore. If this fired, the
recovery point has been outside its objective for at least ten minutes already.

## Why `absent()` is the condition rather than defensive dressing

A rule stated only as a threshold is silent while its series is missing, and **a missing series is the
more serious reading**: it means no backup has ever run, or the timer is not installed. A deployment
that has never backed up is exactly the deployment this alert must fire on.

## Surviving capability

- **Everything in the product works.** This is not an outage.
- What is missing is the copy. Which copy, and therefore how much is at risk, is the table above.

## First checks

Both timestamps are written into the **node exporter's textfile collector** by processes that have since
exited, so there are three separate things that break and they look identical from Prometheus:

1. **The job did not run.** Check the timer.
2. **The job ran and failed.** Check its log. A failed run writes no timestamp, which is deliberate.
3. **The job ran, succeeded, and the timestamp did not reach Prometheus.** Check the file, the
   exporter's flag, and the scrape target.

```
systemctl list-timers 'syncr-*'                  # the three timers, and when each next runs
systemctl status syncr-backup.service            # the last run's exit status and output
journalctl -u syncr-backup.service -n 50         # what it said
journalctl -u syncr-walship.service -n 50
```

```
node_textfile_scrape_error                       # 1 when the exporter could not parse a file
up{job="node"}                                   # the exporter itself
```

Rule out the third case first, because it is the one where nothing is wrong with the data:

```
docker compose $OPS run --rm ops ls -la /var/lib/node_exporter/textfile
```

Both files should be there:
`syncr_backup_last_success_timestamp_seconds.prom` and
`syncr_wal_archive_last_success_timestamp_seconds.prom`.

## What the backup refuses on, and what each refusal means

Every one of these writes no timestamp and exits non-zero, so the message is in
`journalctl -u syncr-backup.service`:

| Message | What it means |
|---|---|
| `fingerprint.json does not exist` / `is Ns old` | The reading step failed. The dump refuses rather than uploading an archive with a stale description of it |
| `is N bytes, under the 1024-byte floor` | `pg_dump` succeeded and wrote nothing. **Look for a full disk or a closed pipe before looking at Postgres** |
| `does not begin with PGDMP` | Not a Postgres archive at all |
| `the dump carries no data entry for [...]` | The archive is of another database, or schema-only |
| `names no remote` / `configured as type 'local'` | The bucket is a directory on this host. A backup on the same disk as the database is not a backup |
| `does not exist, so there is no recipient` | The public key is missing. The dump is never uploaded in the clear |
| `is not in a listing of N backups` | Retention refused, and deleted nothing: the listing is not of the location the upload went to |
| `retention would delete <name>, the newest copy` | Refused, and deleted nothing |

And the shipper's own:

| Message | What it means |
|---|---|
| `Postgres last FAILED to archive at ...` | `archive_command` is failing, so segments are piling up in `pg_wal` and **the staging volume is empty for the wrong reason**. Check the `wal-archive` volume's permissions; `python3 -m ops.prepare` establishes them |

## The repair

```
just backup-now            # the fingerprint, then the dump. Both steps, in order
just wal-ship              # every staged segment
```

Then confirm the figures moved rather than assuming:

```
docker compose $OPS run --rm ops cat \
  /var/lib/node_exporter/textfile/syncr_backup_last_success_timestamp_seconds.prom
```

The alert clears within one scrape interval plus the 10-minute window.

## After the repair

**Run the drill.** A backup path that has just been repaired is a backup path whose output nobody has
restored: `restore-from-backup.md`, which takes under a minute and touches nothing.

## Not verified

- **The textfile collector has not been observed serving either file on a deployed host.** Both are
  written by a real run of the real code locally, and `node_textfile_scrape_error` has never been
  observed non-zero here.
- **`journalctl` output above is what systemd will show**, not what it has shown: no timer has run on a
  deployed host.
