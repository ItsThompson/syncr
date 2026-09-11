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

**The figure is the rule's own, and every copy of it here is crossed against the rule.**
`deployments/prometheus/alerts.yml` declares the threshold and the wait on the `AssemblySlow` rule,
`tests/test_alert_rules.py` asserts that literal, and `tests/test_assembly_runbook.py` asserts this
file's title, trigger block, heading and prose against the rule's own expression. A retune moves every
one of them or the suite fails.

It bounds the **whole interaction** rather than the assembly alone. The assembly's own budget is p95
under 100 ms on a warm cache: `plans/assembler.py` states it, and `core/db_metrics.py` cuts the read
histogram's buckets to it, so a single read past 100 ms has spent the whole budget in one call. A p99
assembly that has reached 150 ms means the interaction it sits inside is already over budget, because a
pin does more than assemble.

So this threshold is not "the assembly is slower than we would like". It is "the interaction is over
budget and the assembly is why".

**Both figures were set against eleven repository reads, and eleven was never counted.**
`plans/assembler.py` counts what the assembly actually does: `RESOLUTION_COUNT` is **19** resolutions
over `REPOSITORY_READ_COUNT` **21** repository reads, and the api suite crosses both constants against
the method itself. Neither the 100 ms budget nor this threshold has been re-derived against 21, so read
the threshold as the point where the interaction is over budget and not as a figure today's read count
justifies.

## Surviving capability

- **Every verdict and every week view is still correct.**
- Solving and projecting are unaffected: the worker's assemblies are a different series, labelled
  `caller="worker"`.
- What has degraded is **every screen that reads a week** and every pin that computes a verdict.

## First checks

The assembly is repository reads, so start with the per-read timings. **The `repository` label is on
the database family and not on the per-method one:** `syncr_db_query_duration_seconds` carries
`repository` and `method`, and the System dashboard draws this query over a shorter window.

```
topk(5, histogram_quantile(0.99,
  sum by (le, repository, method) (rate(syncr_db_query_duration_seconds_bucket[30m]))))
syncr_db_pool_in_use
```

The pool is bounded at **10** connections per process, `POOL_SIZE` 5 plus `MAX_OVERFLOW` 5 in
`core/db.py`, and a request waits **30 seconds** for one before it fails. The gauge is read per
process, so read it per `instance`.

| What you find | What it means |
|---|---|
| One repository dominates | That read is the regression, and the list below names what it resolves. It is the usual case, and it is usually a missing index after a migration |
| `syncr_db_pool_in_use` at 10 | The assembly is waiting for a connection rather than for the database. Pool exhaustion presents exactly like a slow query |
| Every repository is up together | Look at the database, not the code: `pg_stat_activity`, and container memory on the System dashboard |
| Nothing is up, but the assembly is | The cost is between the reads, or in the one read that registers no series of its own. Check whether the week has many more commitments than it did |

## What the assembly reads, in order

Twenty-one reads over nineteen collaborators, in the order one assembly performs them. Each row is the
series the read histogram registers, so a row of the panel above is a row of this table.

| # | Series | What it resolves |
|---|---|---|
| 1 | `SettingsRepository.read` | the home zone, which the week's span and each day's active zone resolve against |
| 2 | `TravelOverrideRepository.list_all` | the overrides that move a day's zone across a travel boundary |
| 3 | `WeekInputVersionRepository.current` | the input version, from which the solve seed derives |
| 4 | `PlanRepository.latest_approved` | the churn baseline: the last revision the user approved, or never-approved |
| 5 | `StoredPlacements.read` | what the week already holds: the live plan, its pins and its outcomes |
| 6 | `OffPlanPeriodRepository.for_span` | the declared off-plan periods, over this week and the one before it |
| 7 | `RoutineRepository.list_all` | the routines the frame materializes from, and the occurrences this week inherits |
| 8 | `WeekAdjustmentRepository.for_week` | the PRECEDING week's approved concessions, which its inherited occurrences are resolved under |
| 9 | `HabitRepository.list_all` | the habits a template entry binds and the cadence expands |
| 10 | `WeekPatternRepository.read` | the week pattern, which names each day's type |
| 11 | `DayTypeRepository.list_all` | the day-type names each materialized entry carries beside its content |
| 12 | `TemplateRepository.list_all` | the template entries those day types materialize |
| 13 | `WeightSetRepository.active` | the duration multipliers, gated by maturity |
| 14 | `HabitOutcomeLog.read` | the habit outcome log, from which each rotation cursor and the outstanding debt derive |
| 15 | `HabitOutcomeLog.latest` | when each habit last recorded an occurrence, from a read bounded to the longest declared interval |
| 16 | `AnchorTypeRepository.list_all` | the anchor types, read before the anchors they widen the span for |
| 17 | `AnchorRepository.overlapping` | the anchors of that widened span, and what each casts into the week |
| 18 | `TaskRepository.list_all` | the eligible tasks, and the demand per deadline |
| 19 | `PreferenceRepository.list_all` | the per-Area daily caps, and the preference chain resolved after the fold |
| 20 | `AreaRepository.list_all` | the Areas whose floor minutes, reservations and gross targets are computed |
| 21 | `WeekAdjustmentRepository.for_week` | this week's approved concessions, folded as a post-pass |

**Three things the rows do not say on their own.**

- **Row 5 registers no series of its own.** `StoredPlacements` composes four repositories, so the
  panel shows its statements under their own names rather than under the seam: `PlanRepository.latest`,
  `SettingsRepository.read`, `PinRepository.for_week` and `BlockOutcomeRepository.for_span`. So
  `SettingsRepository.read` is observed twice in one assembly, at row 1 and again inside row 5.
- **Row 14 is bounded by the habits, not by the week, and the cursor owns what remains of it.** It
  reads every outcome the tenant's habits hold, because the rotation cursor counts completions over
  the whole log and survives no narrower read -- and whether a habit ever recorded anything feeds
  the interval due rule whatever its binding source. Outstanding debt no longer derives here at
  all: it is stored on the habit row (``habits.charged_misses``) and restated by the outcome write,
  so the figure a week's make-ups come from does not grow with the tenant's history.
- **Row 15 asks one question and reads recent history only.** The interval cadence's due rule needs
  when each habit last occurred, which no occurrence older than the longest declared interval can
  answer, so the read carries an `occurred_at` window beside the habits predicate row 14 states.
- **`WeekAdjustmentRepository.for_week` is read twice**, at rows 8 and 20, because each week's
  concessions have to be resolved as that week resolves them or the two weeks disagree about how long
  one night was.

## The comparison that separates code from data

```
histogram_quantile(0.99, sum by (le) (rate(syncr_assembly_duration_seconds_bucket{caller="maintainer"}[30m])))
```

The maintainer assembles the same weeks on its own cadence, roughly **288 times a day**, which is the
figure `horizon/config.py` states for its second duty. Its assemblies carry `caller="maintainer"`, and
the solve worker's are a third series again. If the maintainer's p99 moved at the same time as the
request path's, the cause is the data or the database and not the request path. If only the request path
moved, look at what the request does that the maintainer does not.

## Still to be written

- A decomposition of the assembly into its stages. Today it is one histogram, so a regression is
  visible but not attributable without going to the per-read timings and inferring.
- Which of the twenty-one reads are avoidable. The order is above; nothing yet says which of them could
  be composed into fewer statements.
- A load-shedding or caching answer, if the cost turns out to be inherent rather than a regression.
