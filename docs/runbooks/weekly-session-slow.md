# p95 weekly-session payload latency is over 400 ms

## Trigger

`WeeklySessionSlow` fires. It is a **warning**.

```
histogram_quantile(0.95,
  sum by (le) (rate(syncr_http_request_duration_seconds_bucket{route="/api/v1/reviews/week/{iso_week}"}[30m]))) > 0.4
```

It waits **15 minutes**.

## What the read is

The weekly session's payload is one read: `GET /api/v1/reviews/week/{iso_week}`. It composes the
week view the Week screen already shows, then adds the review half: the retrospective over the
preceding quarter, the chronic-skip run, the repeated-collision grouping and the raise candidates.
One request, one route template, so every week's session read is one series.

## Why 400 ms

**The budget is stated once, in `reviews/config.py` as `SESSION_P95_BUDGET_SECONDS`, and this file,
the alert threshold and that constant are crossed against each other by the suite.** A retune moves
the constant first.

The arithmetic:

```
300 ms   the week view it composes, at its own stated p95 budget
         (`tests/test_week_view_integration.py` states and measures it)
+ 100 ms everything the review half adds, held to one read bucket:
         two span reads over the reviewed quarter, at most thirteen stored documents,
         seven single-statement fact reads (`reviews/session_sources.py`),
         three repository reads -- every one inside a `core/db_metrics.READ_BUCKETS` bucket
= 400 ms
```

The figure is a p95 because the budget itself is stated as a p95, which is why this alert reads
`histogram_quantile(0.95 ...)` where the probe and assembly alerts read p99.

## Surviving capability

- Nothing is lost and nothing is wrong with the plan. Verdicts, week views, solving and projecting
  all still work at their own pace.
- What has degraded is opening the weekly session, whose one read is slower than its budget.

## First checks

The payload's cost is dominated by the week view it composes, so start where an assembly regression
starts. The per-read timings are on the database family; the assembly itself is on its own family.

```
histogram_quantile(0.95,
  sum by (le) (rate(syncr_http_request_duration_seconds_bucket{route="/api/v1/reviews/week/{iso_week}"}[30m])))
histogram_quantile(0.99,
  sum by (le) (rate(syncr_assembly_duration_seconds_bucket{caller="request"}[30m])))
topk(5, histogram_quantile(0.99,
  sum by (le, repository, method) (rate(syncr_db_query_duration_seconds_bucket[30m]))))
```

| What you find | What it means |
|---|---|
| `syncr_assembly_duration_seconds` is up too | The week view underneath is the cost. Start at `assembly-slow.md`; this alert is its symptom |
| One repository dominates the read histogram | That read is the regression. The review half's reads are named below |
| Only the session route is up | The review half grew: check the quarter's document count and the seven fact reads |
| The pool gauge sits at its ceiling | The read is waiting for a connection, not doing work. Read `assembly-slow.md`'s pool section |

The review half's reads, all registered under their own names on the read histogram:
`PlanRepository.latest` (once per stored week of the quarter, through the history reader),
`BlockOutcomeRepository.for_span` and `OffPlanPeriodRepository.for_span` (one statement each for
the whole quarter), and the seven single-statement readers `reviews/session_sources.py` composes.

## A known gap

One HTTP series covers both halves of the payload, so "the week view got slower" and "the review
half got slower" are told apart by inference, not by a panel: read the comparison table above
against `assembly-slow.md`. The budget is stated over the whole payload, and stays stated that way
until a decomposition panel exists; nothing in this file promises one today.
