# No successful backup in 36 hours

> **This alert fires on every deployment today, and that is the correct reading rather than a
> defect.** Nothing writes `syncr_backup_last_success_timestamp_seconds` yet: the nightly backup is
> **ticket 58**. Until it lands, the `absent()` term is true and this alert fires ten minutes after
> the monitoring stack starts. Either sequence the stack after ticket 58, or post an Alertmanager
> silence for `BackupStale` **with an expiry**. Do not remove the `absent()` term: that restores the
> silence this alert exists to break.

## Trigger

`BackupStale` fires. It is **critical**, and it is the only alert in this deployment about data that
cannot be recovered.

```
absent(syncr_backup_last_success_timestamp_seconds)
or time() - max(syncr_backup_last_success_timestamp_seconds) > 129600
```

129600 seconds is **36 hours**, which is one nightly run plus most of a day of grace. It waits
**10 minutes**.

## Why `absent()` is the condition and not defensive dressing

A rule stated only as a threshold is silent while its series is missing, and **a missing series is the
more serious reading**: it means no backup has ever run. A deployment that has never backed up is
exactly the deployment this alert must fire on, so the absent term is the alert's primary case rather
than an edge one.

## Surviving capability

- **Everything in the product works.** This is not an outage.
- WAL archiving may still be running, in which case the exposure is bounded by the last archived
  segment rather than by the last dump. Check that before treating this as total data loss.

## First checks

The timestamp is written into the **node exporter's textfile collector** by the backup job, so there
are three separate things that break and they look identical from Prometheus:

1. **The backup did not run.** Check the timer or cron entry on the host.
2. **The backup ran and failed.** Check its own log. A failed run must not write the timestamp.
3. **The backup ran, succeeded, and the timestamp did not reach Prometheus.** Check that the file
   exists in the textfile collector directory, that the node exporter is configured with
   `--collector.textfile.directory`, and that the `node` scrape job is up.

The third case is the one to rule out first, because it is the one where nothing is actually wrong
with the data:

```
node_textfile_scrape_error         # 1 when the exporter could not parse a file in that directory
up{job="node"}                     # the exporter itself
```

## What to do

Once ticket 58 exists, the repair is to run the backup by hand and confirm the timestamp moves. Until
then the honest answer is that this deployment has no backup, and the action is ticket 58 rather than
anything at 03:00.

## Still to be written

- **The backup job itself, its schedule, and where it writes.** Ticket 58. This runbook names the
  metric it must write, `syncr_backup_last_success_timestamp_seconds`, and the alerting suite
  declares that name as externally produced so a rename on either side fails a gate.
- **Restoring from a backup.** The procedure, the expected downtime, and how to verify a restore
  before trusting it. All of it depends on the backup format ticket 58 chooses.
- Whether WAL archiving is configured on this deployment at all, which decides whether the surviving
  capability above is true.
