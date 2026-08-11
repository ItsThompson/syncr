# The nightly learning run has failed, or has never reported

> **This alert stops firing once the timer is installed, and that install is a deployment step rather
> than another ticket.** The container is a Compose one-shot (`just learn-once`) driven by
> `deployments/systemd/syncr-learning.timer` at 03:00, and it writes its exposition into the textfile
> collector before exiting, because a container that has exited cannot be scraped. On a host where the
> timers are not installed yet, no run has ever reported, the `absent()` term is true, and this fires an
> hour after the monitoring stack starts. Install the timers (`deploy-and-rollback.md`, step 10) or post
> an Alertmanager silence **with an expiry**. Do not remove the `absent()` term: that restores the
> silence it exists to break.

## Trigger

`LearningJobFailed` fires. It is **info**, the only alert in this deployment at that severity.

```
absent(syncr_learning_run_duration_seconds_count)
or increase(syncr_learning_run_duration_seconds_count{outcome="failed"}[24h]) > 0
```

It waits **1 hour**.

## Why it is info and why it exists at all

**Benign, but it should not be invisible.** The solver keeps working with the weight set already in
force, so every plan is still produced and still correct. The parameters are slightly stale, which is
the whole cost. Nothing degrades for the user and there is nothing to do at 03:00.

It is an alert rather than nothing because a nightly job that has silently stopped is indistinguishable
from one that is working, and the drift is invisible: plans stay correct while the weights stop
improving.

## Surviving capability

- **Every plan is still produced and still correct**, using the weight set already promoted.
- Solving, projecting, pinning and confirming are all unaffected.
- What is stale is the weights, by one night per missed run.

## How a run reports at all

The learning run is a **separate process in a separate distribution**, and it is not scraped: a process
that exits cannot be scraped. It writes its own exposition to a file the node exporter's **textfile
collector** reads, at `syncr_learning.prom` in `textfile_collector_dir`, before exiting.

That is three things that can break and they look identical from Prometheus:

1. **The run did not happen.** The timer is not installed, or it is disabled:
   `systemctl list-timers 'syncr-*'`.
2. **The run happened and failed.** It exits non-zero when a tenant's pass failed, and it writes its
   figures **before** exiting, so the series is present rather than absent. **Prometheus cannot tell you
   whether the run succeeded or failed.** The duration family carries no `outcome` label, so a night that
   ran and failed and a night that ran and succeeded are the same series with the same value. The exit
   status is systemd's record and nothing scrapes it: `systemctl status syncr-learning` and the run's own
   log are where the difference is readable.
3. **The run happened, succeeded, and the file did not reach Prometheus.** Check the textfile directory,
   the `--collector.textfile.directory` flag, and the `node` job.

Rule out the third first, because in that case nothing is wrong:

```
node_textfile_scrape_error       # 1 when the exporter could not parse a file in that directory
up{job="node"}
syncr_learning_run_duration_seconds_count
```

## First checks when a run has failed

**Not from Prometheus.** The duration family has no `outcome` label, so no query separates a failed night
from a successful one. Both readings below are on the host:

```
systemctl status syncr-learning   # the exit status of the last run, which is where the failure is
systemctl list-timers syncr-learning
```

The metric answers only whether a run reported at all:

```
syncr_learning_run_duration_seconds_count
```

Then the run's own log. The events to look for are `learning.tenant.failed`, which carries the
traceback for the tenant whose pass raised, and `learning.run.failed`, one line per failure before the
non-zero exit. `learning.run.finished` carries the tenant and failure counts either way. A failed pass
for one tenant does not stop the others: the run continues and reports the failure.

## What to do

Nothing urgent, and nothing at night. A missed night is a night of stale weights. If runs fail
repeatedly, the weights are frozen at the last promoted set, which is a correct state rather than a
broken one, and the investigation is a normal-hours one.

## Still to be written

- **The timer has never run on a deployed host.** The unit and the timer exist
  (`deployments/systemd/syncr-learning.*`) and `just learn-once` is what they call; no deployment
  exists to have executed either.
- The diagnosis of a failing pass: which stage of the learning run failed and what a candidate weight
  set that was not promoted means. The run logs its promotion decision; nothing explains a rejection.
- Whether a run that fails for every tenant should be a warning rather than info. It is info today
  because the cost does not change with the number of failing tenants: the weights are stale either way.
