# A week inside the projection horizon has no plan

## Trigger

`HorizonNotMaintained` fires. It is a **warning**.

```
max(syncr_horizon_weeks_without_plan) > 0
or increase(syncr_horizon_tenant_failures_total[2h]) > 0
```

It waits **2 hours**, which is eight maintainer passes.

## What the user sees

**A calendar that goes blank at a week boundary.** The failure is at the edge of the horizon, not in
the middle, so the user does not notice until they scroll forward to a week that should have a plan and
finds nothing. That is why this is a warning and not a page: it is a future problem, and there are two
hours of maintainer passes before it is reported at all.

## The two halves are different failures

| Half | What it means |
|---|---|
| `syncr_horizon_weeks_without_plan > 0` | The maintainer is running and **not keeping up**, or a specific week cannot be planned. The gauge is the count of weeks in range with no plan |
| `syncr_horizon_tenant_failures_total` increasing | The maintainer's pass is **raising**. It never advances the horizon at all, and its contained fault is counted rather than recorded on the gauge, so the gauge alone would read healthy |

The second half exists because of that last clause: a maintainer failing on every tick leaves the gauge
frozen at its last value, and its last value is the healthy one.

## Figures

| Figure | Value | Where |
|---|---|---|
| How often the maintainer plans | **15 minutes** | `MAINTAINER_INTERVAL`, `horizon/config.py` |
| How long the alert waits | **2 hours** | `for:` on the rule |
| Default horizon | **14 days** | `HORIZON_DAYS_DEFAULT`, `calendars/config.py` |

Fifteen minutes bounds the lag between a week entering the horizon and its plan existing. The two-hour
`for` window is deliberately many passes: the gauge is expected to be non-zero briefly whenever the
horizon extends or the user changes `horizon_days`.

## Surviving capability

- **Every week that HAS a plan is still solved, projected and correct.**
- Pinning, confirming and the live verdict all work on those weeks.
- The failure is at the edge: the calendar will go blank at a week boundary the user has not reached
  yet.

## First checks

```
syncr_horizon_weeks_without_plan
increase(syncr_horizon_tenant_failures_total[2h])
histogram_quantile(0.99, sum by (le) (rate(syncr_maintainer_tick_duration_seconds_bucket[2h])))
```

1. **Is the worker alive?** If `DatabaseUnreachable` is firing, that is the cause and this is
   downstream: it is a named inhibit rule, so this should already be suppressed.
2. **Is the pass raising?** Read the worker log for `horizon.tenant.failed` and `horizon.week.failed`.
   The first is the contained per-tenant fault the second half of the rule counts; the second names the
   week.
3. **Is a specific week unplannable?** `horizon.week.not_ready` is the log event for a week the
   maintainer chose to skip. A week whose inputs are legitimately unsatisfiable is a different problem
   from a maintainer that is broken, and it is the feasibility question rather than a fault.
4. **Did the user just extend the horizon?** A change to `horizon_days` makes the gauge non-zero
   legitimately, for up to one pass per new week.

## Recovery

The maintainer is idempotent and self-healing: it plans whatever is in range and has no plan, every 15
minutes. So for anything other than an unplannable week, the recovery is to fix the cause and wait one
pass. There is nothing to run by hand and no queue to drain.

If a single week is the blocker, `SolveFailing` is likely firing too, and `solve-failing.md` is where
the reproduction lives.

## Still to be written

- What to do about a week whose inputs are genuinely unsatisfiable. That is the feasibility probe's
  answer and the probe does not exist yet, so today such a week keeps the gauge non-zero indefinitely
  and this alert firing with no available repair.
- Whether the maintainer should distinguish "cannot plan this week" from "has not planned it yet" on
  the gauge. It does not, and the two have different urgencies.
