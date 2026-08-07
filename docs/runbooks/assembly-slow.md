# p99 week-assembly duration on the request path is over 150 ms

## Trigger

`AssemblySlow` fires. It is a **warning**.

```
histogram_quantile(0.99,
  sum by (le) (rate(syncr_assembly_duration_seconds_bucket{caller="request"}[30m]))) > 0.15
```

It waits **15 minutes**.

## Why this is separate from `ProbeSlow`

**The assembly, not the probe, is the dominant cost of a pin.** The probe measures the arithmetic that
sits on top of the assembly; the assembly underneath is a series of repository reads. Without this
alert, a regression in the reads that every live verdict depends on would be invisible to monitoring,
because the probe's own figure would not move at all.

That is the whole reason two alerts exist over one interaction.

## Why 150 ms

It is the **`POST /pins` end-to-end budget** from `19-nonfunctional.md`, stated against the whole pin
rather than against the assembly's own p95 budget. A p99 assembly that has reached the end-to-end
budget means the budget is already being missed, because the pin does more than assemble.

So this threshold is not "the assembly is slower than we would like". It is "the interaction is over
budget and the assembly is why".

## Surviving capability

- **Every verdict and every week view is still correct.**
- Solving and projecting are unaffected: the worker's assemblies are a different series, labelled
  `caller="worker"`.
- What has degraded is **every screen that reads a week** and every pin that computes a verdict.

## First checks

The assembly is repository reads, so start with the per-repository timings:

```
topk(5, histogram_quantile(0.99,
  sum by (le, repository) (rate(syncr_method_duration_seconds_bucket[30m]))))
syncr_db_pool_in_use
syncr_db_pool_size
```

| What you find | What it means |
|---|---|
| One repository dominates | That read is the regression. It is the usual case, and it is usually a missing index after a migration |
| `syncr_db_pool_in_use` at `syncr_db_pool_size` | The assembly is waiting for a connection rather than for the database. Pool exhaustion presents exactly like a slow query |
| Every repository is up together | Look at the database, not the code: `pg_stat_activity`, and container memory on the System dashboard |
| Nothing is up, but the assembly is | The cost is between the reads. Check whether the week has many more commitments than it did |

## The comparison that separates code from data

```
histogram_quantile(0.99, sum by (le) (rate(syncr_assembly_duration_seconds_bucket{caller="worker"}[30m])))
```

The maintainer assembles the same weeks on its own cadence, roughly **288 times a day**. If the worker's
p99 moved at the same time as the request path's, the cause is the data or the database and not the
request path. If only the request path moved, look at what the request does that the maintainer does
not.

## Still to be written

- A decomposition of the assembly into its stages. Today it is one histogram, so a regression is
  visible but not attributable without going to the per-repository timings and inferring.
- Which repository reads the assembly performs, in order, and which are avoidable. That list would turn
  the table above from a diagnosis into a checklist.
- A load-shedding or caching answer, if the cost turns out to be inherent rather than a regression.
