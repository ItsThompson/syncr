# A solve is failing

## Trigger

- The `SolveFailing` alert fires. It watches solve failures over 30 minutes and is a **warning**, not
  a page.
- Or the Week screen reads `stale`, which is what it says when the last operation for that week
  failed terminally.

## What it means

A solve could not complete. The previous live plan for the week is untouched and still projected, so
the user has a plan; it simply predates their latest changes. That is why this is a warning: a failed
solve loses nothing, and the alert's own annotation says so.

Two failures are **not** this alert and must not be diagnosed as it:

| Status | What it is |
|---|---|
| `superseded` | The user's own later edit displaced the solve, its result was discarded, and a follow-up is already running. **Not an error.** It is the expected outcome of editing quickly, and a sustained ratio above roughly 0.3 is a signal about the debounce window rather than about a fault: see `SupersededRatioHigh` |
| `failed` with `error.code` of `lease_expired` | The worker holding the work stopped. The reaper returns it to the queue. See `stuck-operation.md` |

## Retry and retention

| Rule | Value |
|---|---|
| Attempts before a failure is terminal | 3 |
| Backoff between attempts | 30 seconds, doubling with the attempts already spent |
| A terminal failure on a week that already has a plan | Changes nothing. The previous plan stays, and it is better than a materialized one |
| A terminal failure on a week with **no** plan | `materialize` runs instead, appending a revision whose reason is `materialized`, so the horizon is never left with a hole |
| How long a failed operation is kept | 90 days, because a failure is diagnostic |
| How long a succeeded or superseded one is kept | 30 days |

## Reproducing the failure locally

**A failed operation persists the resolved inputs it read**, in `failed_input_snapshot`. That column
is the whole mechanism, and it is what makes the product's hardest component its most debuggable one:
load the snapshot and call the solver.

It is written **only** when the status is `failed`, which the table's own constraint enforces, and
only on the last attempt: a retried attempt returns the row to `pending`, so an earlier attempt's
snapshot would have to be cleared again. It is bounded to one week of resolved inputs and it is
pruned with the operation at 90 days.

### Why `input_version` cannot do this job

`input_version` is a **counter**, not a snapshot. Re-running the assembler against the week yields
whatever the state is now, not the state that failed: every mutation since has moved the plan, the
backlog, the anchors and the concessions. So a reproduction built from the counter reproduces a
different week and, on the ordinary path, succeeds. That is the failure mode this column exists to
prevent, and it is why the snapshot is stored rather than derived.

### Find the operation

```
GET /api/v1/operations?status=failed&kind=solve
```

Each row carries `id`, `attempt`, `error.code`, `error.message`, `target.isoWeek`, and `statement`.
Take the `id`.

### Read the snapshot

The snapshot is deliberately absent from every ordinary read of an operation: it is a whole resolved
week, and the wire shape and the worker both want the status and the attempt instead. It is read by
identifier, and only by something that wants it. A `null` here means no solve has failed through the
runner, not that a snapshot was dropped: the column is written only on a terminal failure, which the
table's own constraint enforces.

```
docker compose exec worker python - <<'PY'
import asyncio, json, sys
from syncr_api.solving.repository import OperationRepository
from syncr_api.worker.main import build_context

OPERATION_ID = sys.argv[1]
TENANT_ID = sys.argv[2]

async def read() -> None:
    context = build_context()
    try:
        async with context.database.sessionmaker() as session:
            found = await OperationRepository(session, TENANT_ID).read_failed_input_snapshot(
                OPERATION_ID
            )
            json.dump(found, sys.stdout, indent=2, default=str)
    finally:
        await context.database.engine.dispose()

asyncio.run(read())
PY
```

### Rebuild the inputs

The snapshot is JSON and the solver takes a `SolveInputs` value. `inputs_of` is the reader that
turns one into the other, and it is the mirror of the writer that stored the snapshot: it refuses a
field it holds no form for, so a rebuilt value is the inputs that failed or a stated refusal, never
a silently defaulted one.

```python
from syncr_api.solving.stored_inputs import inputs_of

inputs = inputs_of(found)
```

### Call the solver on it

The solver is pure: it performs no lookup, reads no clock, and draws on no randomness, so a snapshot
plus a weight set is the whole input. Two solves of one snapshot produce one document, byte for byte.

For the materialization path, which is what runs when a terminal failure leaves a week with no plan,
the call takes no weight set at all, because nothing is being chosen:

```python
from syncr_solver import MaterializeCause, materialize

document = materialize(inputs, cause=MaterializeCause.SOLVE_FAILED)
```

The `cause` label is what tells this path apart from the two ordinary ones on
`syncr_materialize_total`, and a non-zero `solve_failed` count is exactly this runbook's subject: a
solver fault surfacing as a degraded plan rather than as an outage.

## Still to be written

- The solver's own diagnosis: which constraint or which term to look at for a given exception.
- What to do when a solve fails for a week whose inputs are legitimately unsatisfiable, which is the
  feasibility probe's answer rather than a fault.
