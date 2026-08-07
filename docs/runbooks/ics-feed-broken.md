# A calendar source has not been read for 24 hours

## Trigger

`SourceStale` fires. It is a **warning**.

```
max(syncr_source_staleness_seconds) > 86400
```

It waits **30 minutes**. Read as a **maximum over sources**, so one dead feed fires it: an average
would let a healthy feed hide one that has stopped.

## Two figures make this alert quiet on the ordinary path

| Figure | Value | Where |
|---|---|---|
| How often a source is polled | **15 minutes** | `SYNC_INTERVAL`, `calendars/config.py` |
| How long the alert waits | **30 minutes** | `for:` on the rule |

The `for` window is two polls. A single missed poll cannot fire this, and a source that resumes on the
next tick clears it without anyone being told. `test_runbook_figures.py` crosses those two so the
relationship cannot drift silently.

## Which sources publish this reading at all

**Only sources the user has INCLUDED.** An excluded source publishes no staleness series, because the
user asked for zero anchors from it: going unread is the expected outcome of their own instruction, and
this alert reads `max()`, so any reading from an excluded source would stick it firing forever. An
excluded source still publishes `syncr_anchors_current` at **0**, which is a true reading nothing
alerts on.

A source that has **never** succeeded is measured from its `created_at`, so a feed that was never
readable crosses 24 hours a day after it was added rather than never firing at all.

## Surviving capability

- The plan is still solved, projected, and **correct against the commitments syncr last read**.
- Every screen works. Pinning, confirming and the live verdict are unaffected.
- The risk is that those commitments have moved: **a lecture that was cancelled is still being planned
  around.** That is the whole cost, and it is why this is a warning rather than a page.

## First checks

Find which source, because the alert deliberately does not tell you:

```
syncr_source_staleness_seconds > 86400
```

Then read the source's own state:

```
GET /api/v1/calendar-sources
```

Each row carries `lastSuccessAt`, `lastError` and `included`.

| What you find | What it means |
|---|---|
| `lastError` names an HTTP status | The feed URL is refusing. A 404 usually means the timetable was republished at a new URL |
| `lastError` is a parse failure | The feed is being served but is not valid ICS. Some providers serve an HTML error page with a 200 |
| `lastError` is null and `lastSuccessAt` is old | The poll is not running. Check `HorizonNotMaintained` and the worker: if the worker is gone, `DatabaseUnreachable` is the page and this is downstream |
| The source is a **Google** source | See below |

## The Google case, which is not a feed problem

One Google grant serves both the anchor reads and the write target. **A revoked grant fires
`WriteTargetTokenExpiring` at once and this alert 24 hours later**, for one repair: reconnect the
account. That is a named inhibit rule, so if the token alert is firing this one should already be
suppressed. If both arrive, the inhibition is what to investigate.

A Google source on a deployment with **no Google configuration** is a different case and it fires
permanently: the source is included, so the user asked for it, but `build_adapters` returns only the
ICS adapter when `GOOGLE_OAUTH_CLIENT_ID` is empty, and the source is never polled at all. The alert
firing is correct: the two repairs are to configure Google or to remove the source.

## Recovery

- A changed feed URL: `PATCH /api/v1/calendar-sources/{id}`. The next poll clears the alert within 15
  minutes plus the `for` window.
- A source the user no longer wants: exclude it (`PATCH {"included": false}`) or remove it. Either one
  removes the staleness series immediately, on the next state tick.

## Still to be written

- Per-provider diagnosis for the common university timetable systems, which is where most ICS feeds on
  this deployment come from.
- What to do about a feed that intermittently serves an empty calendar. Nothing distinguishes "no
  events this week" from "the feed broke and returned nothing" today.
