# Google write-target token expired

> **Stub.** The trigger, the meaning, and the reconnect path are settled and recorded below. The step-by-step operational procedure lands with the projection writer, which is the code that surfaces this failure. Do not treat the absence of those steps as the absence of a problem.

## Trigger

Either of these means the write target's OAuth token can no longer be refreshed:

- The `WriteTargetTokenExpiring` alert fires. It watches `syncr_write_target_token_age_seconds` past a refresh-failure threshold and is **critical**.
- The in-product banner appears, in oxide, on every screen, with a panel on Settings.

## Why this is the loudest failure in the product

Reading anchors keeps working. Solving keeps working. The plan keeps updating. Only the projection stops, so the calendar on the phone silently freezes at the last successful write while syncr itself looks healthy. The write target exists to get the plan onto the phone, so this failure removes the product's entire delivery mechanism while presenting no symptom in syncr. That is why the notice is a banner rather than a panel, and why the alert is critical rather than a warning.

## Surviving capability, which the notice must state

- Anchor sources still sync, so external commitments are still read.
- The plan is still solved and still correct in syncr.
- Writes to the calendar are failing, so the phone is stale from the timestamp in the banner.

## The reconnect path

Reconnecting is a user action, not an operator action. The banner and the Settings panel each offer a single **Reconnect** action. It restarts the Google authorization flow for the same account, issues a fresh refresh token, and replaces the stored one. Nothing else needs to change: the calendar selection, the write-target role, and the horizon all survive a reconnect, because the token is the only thing that expired.

After reconnecting, the next projection run brings the write target back into agreement with the live plan. Reconciliation is destructive over the horizon, so any event the user hand-created on the target while writes were failing is removed and counted as a foreign deletion.

## Rule out first

Check the app's publishing status in the Google Auth Platform console before investigating anything else. A project with an External audience and a publishing status of `Testing` expires every authorization seven days after consent, and the refresh token with it. If the status has reverted to `Testing`, the token did not fail: Google revoked it on schedule, and reconnecting weekly is the only alternative to publishing the app. See `google-oauth-verification.md`.

## Still to be written

- How to confirm from the logs and metrics that refresh is the failing step, rather than a rate limit or a revoked grant.
- How to read the projection failure count and the last successful write timestamp.
- What to check after reconnecting to prove the write target is current.
- How to distinguish a user-revoked grant, which cannot be recovered without reconnecting, from a transient refresh error, which retries clear.
