# The projection to the write target is failing

## Trigger

`ProjectionFailing` fires. It is **critical**: the plan is not reaching the phone.

```
(increase(syncr_projection_duration_seconds_count{outcome="failed"}[15m]) > 0
  and on() syncr_projection_writes_enabled == 1)
or increase(syncr_projection_tenant_failures_total[15m]) > 0
```

It waits **5 minutes**.

## Read the arming term first

**`syncr_projection_writes_enabled` is what separates "syncr cannot write" from "syncr is not
permitted to write".** A projection refused because writes are switched off is recorded as `failed`
deliberately, and on a deployment with no Google configuration that is every projection. Without the
arming term this alert would fire on every plan change on every such deployment; with it, a refusal is
silent and a real failure is not.

So if this alert is firing, writes ARE enabled and the failure is real. Confirm it anyway, because it
is one query and it tells you which half of the rule fired:

```
syncr_projection_writes_enabled                                        # must be 1
increase(syncr_projection_duration_seconds_count{outcome="failed"}[15m])
increase(syncr_projection_tenant_failures_total[15m])
```

## Which half fired, and why they are different failures

| Half | What it means | Where to look |
|---|---|---|
| `outcome="failed"` | A projection pass ran and reported failure through the reconciliation's own stated failures. The user sees a degradation banner | The operation's error, and the Google API response in the worker log |
| `syncr_projection_tenant_failures_total` | A pass **raised outside** the stated failures. **There is no banner**: the product looks healthy while operations sit `running` until the reaper returns them | The worker log's traceback. This is a bug, not a Google problem |

The second half is the one worth the alert's existence. It is the one projection failure with no
in-product signal at all.

## Surviving capability

- The plan in syncr is **correct and complete**, and every screen still shows it.
- Anchor sources still sync.
- What is stale is the calendar on the phone, from the instant in the banner.

## First checks

1. **Is it the token rather than the write?** If `WriteTargetTokenExpiring` is also firing, that is
   the cause and this is downstream: it is a named inhibit rule, so this alert should already be
   suppressed. Go to `google-token-expired.md`.
2. **Is Google refusing, and with what?** The worker log carries the response. A 403 with
   `rateLimitExceeded` is a different repair from a 401.
3. **Is the calendar still there?** A write target the user deleted in Google fails every write. So
   does a calendar whose sharing was changed.

```
docker compose logs --tail=300 worker | grep -i projection
```

## Surviving-capability check before you intervene

Nothing here is lost. Every projection is idempotent and reconciles from the plan of record, so a
failed pass is retried and a partial pass is completed rather than duplicated. Do not delete calendar
entries by hand to "clean up": the reconciliation is what decides what belongs, and a hand-deleted
entry is restored on the next successful pass.

## Still to be written

- **The Google error taxonomy**: which response codes are retriable and which need the user to act.
  Today the worker log is the only place that distinction is visible.
- What to do when the write target calendar has been deleted in Google, which needs a re-selection
  flow that does not exist yet.
- The per-tenant view. This deployment is single-tenant in practice, so the tenant label on
  `syncr_projection_tenant_failures_total` has one value and the aggregate is the reading.
