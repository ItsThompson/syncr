# Tuning the debounce window

## Trigger

`syncr_solve_superseded_ratio`, or the windowed rate below it, sitting above roughly **0.3** for a
sustained period. Nothing is broken when it does: supersession is the expected outcome of editing
quickly. What a sustained ratio says is that the window does not fit how this user edits.

The window is how long the coordinator waits after a mutation before a solve becomes due. It is
**1500 ms** by default and it is configuration, not a constant: set `SOLVE_DEBOUNCE_MS` and restart
the api and the worker.

## What the window is, and what it is not

A **fixed** window from the FIRST mutation of a burst. A later mutation inside it does not extend it.
That is deliberate: a sliding window would mean a user editing continuously never gets a solve at
all, which is the opposite of the intent. A burst therefore always resolves within one window of its
start.

The window does not affect live feedback. The verdict is computed synchronously and returns in the
mutation's own response, so the user never waits on the window for information: what the window
delays is the new plan, not the answer to "does this week still work".

## How to read the supersession ratio

```
syncr_solve_superseded_ratio
```

A gauge, exported by both the api and the worker, holding the share of that process's finished solves
that were discarded as superseded. It is cumulative over the process's lifetime, so read it after the
process has been up for a day rather than a minute.

The threshold the design is stated against is a **windowed** rate, which the gauge cannot express.
Read that with:

```promql
sum(rate(syncr_solve_total{outcome="superseded"}[1h]))
  / sum(rate(syncr_solve_total[1h]))
```

| Reading | What it means |
|---|---|
| below 0.1 | the window fits how this user edits. Nothing to do |
| 0.1 to 0.3 | ordinary. A supersession is the expected outcome of editing quickly |
| **sustained above 0.3** | the window is too short for this user's editing rhythm |

The design guarantees at most one discarded solve **per window**, not per burst, and the difference
matters when reading the ratio. Inside one window every mutation coalesces into the operation the
first one created, so a burst of two hundred edits inside 1500 ms costs one solve at most. Editing
that continues past the window opens a new one each time a solve starts, so sustained editing loses
roughly one solve per solve-duration. A sustained ratio above roughly 0.3 therefore does not mean
the mechanism is failing: it means bursts are being cut short, the window is expiring mid-burst, a
solve starts, and the next edit displaces it.

**One cause of a supersession is not a window question at all, and tuning the window does nothing for
it.** A tradeoff request never coalesces and is never debounced: it closes whatever solve is in flight,
running included, and takes its place, because a proposal that does not contain the concession is not
an answer to what the reader asked. So a reader working through the tradeoffs an infeasible week offers
produces one supersession per request whatever the window is. Read
`syncr_solve_taken_over_total` beside the ratio before changing the value: it counts the solves whose
write was discarded mid-flight, which is the shape a tradeoff request leaves and a coalesced burst
does not.

## What the 1500 ms was measured against

The default is confirmed after a twelve-pin editing burst ran against the deployed E2E stack with all thirteen trigger rows wired. After a fresh worker restart, the worker reported **0 superseded solves from 4 finished solves**, a **0.0** supersession ratio. Three solves materialized the fixture and the fourth resolved the burst. The reading is below 0.1, so the default stays at 1500 ms.

| Figure | Provenance |
|---|---|
| a twelve-pin editing burst produces 0 superseded solves from 4 finished solves | measurement of this deployment: `just e2e-only tests/s10-burst.spec.ts`, then the worker's `/metrics` |
| a weekly-session burst has 3 to 8 second gaps | interview reading of how the product is used |
| a solve is budgeted under two seconds | measurement of the solver budget on its reference workload |

**The first row is now a measurement of this deployment.** The session-gap range remains an interview reading. This one burst confirms the default's coalescing behavior; read the one-hour rate over ordinary editing before changing the deployment setting.

## Changing the value

```
# .env
SOLVE_DEBOUNCE_MS=2500
```

Restart the api and the worker. Nothing is migrated and nothing is lost: operations already scheduled
keep the due instant they were given, and the next mutation uses the new window.

| Direction | What it buys | What it costs |
|---|---|---|
| **longer** | fewer discarded solves during a burst | the plan takes longer to catch up after the last edit |
| **shorter** | the plan follows an edit sooner | more solves start mid-burst and are discarded |

Two values bound the sensible range from either end. Below roughly 1000 ms the window is shorter than
a single drag, so one drag produces two solves and the first is always wasted. Above roughly 5000 ms
the gap between edits in a weekly session (3 to 8 seconds) falls inside the window, so a whole session
produces one solve at the end rather than a plan that keeps up with it.

## What a high ratio is NOT

**It is not an error rate.** `superseded` is reported distinctly from `failed` throughout the product,
because it is the expected outcome of editing quickly: the user's own later change displaced a solve
and a follow-up is already running. Nothing was lost and the previous plan stayed live throughout.

**It is not a correctness signal.** The conditional write is what makes a stale plan unadoptable, and
it does not depend on the window at all. A window of zero would be correct and wasteful; a window of
an hour would be correct and useless. What the window decides is only how much work is discarded.

## Figures this runbook quotes

| Figure | Where it comes from |
|---|---|
| 1500 ms | `DEFAULT_SOLVE_DEBOUNCE_MS` in `syncr_api.core.settings` |
| 0.3 | the supersession-ratio threshold in `18-observability.md` |
| one discarded solve per window | the single-flight invariant, held by a partial unique index |
| a solve under two seconds | `syncr_solver.budget`, whose two bounds were measured against it |
