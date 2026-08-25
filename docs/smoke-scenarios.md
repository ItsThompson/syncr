# The 37 smoke scenarios

Section 20 of the specification numbers 37 scenarios, and section 22's done-criteria table is written
against them. This file states, for each one, whether it is automated, manual, or manual with a seeded
precondition, so that table maps to something a person can run or a job can fail on.

A scenario is **automated** when a test in `e2e/tests/` asserts its observations and the test title
names its number. A scenario is **manual with a seed** when a `just seed-*` recipe puts the stack in
the state it needs and the observations are written out below for a person to check. A scenario is
**manual** when it needs a real external provider or a real host.

## How to run any of it

```
just e2e-setup            # once: the suite's dependency tree and the browser it drives
just e2e-up               # the stack, migrated, on http://localhost:57080
just seed-reference       # or any other seed-* recipe: each loads one fixture from nothing
just e2e                  # the whole suite
just e2e-only S10         # one scenario or one file, by title or path
just lint-e2e             # prettier, and the two checks that a statement matches the suite
just e2e-down             # the stack and its volumes
```

**This table is checked against the suite rather than trusted.** `just lint-e2e` runs
`e2e/scripts/check-scenarios.ts`, which crosses this table against the tests Playwright reports it would
run. It reads three of the table's four columns: every automated row must have a test naming its scenario
and must name the spec file that test lives in, every scenario a test names must be marked automated here,
and every repository path and `just` recipe cited in the Where column must resolve. The observation column
is prose and is not bounded. Its first version read two columns and its first run found four disagreements,
one of them a row claiming an assertion no file in the suite made.

**A second statement, keyed on the file rather than on the scenario, lives at `e2e/scenarios.md`** and is
checked by `e2e/scripts/check-spec-scenarios.ts` in the same run. This table cannot account for a spec file
that drives none of the 37, because it has no row to hang one on, and nothing in it is keyed on the set of
files, so it cannot notice a new spec at all. That one is: every `*.spec.ts` in `e2e/tests/` has a row
there, and the numbers a row states are crossed against the numbers that file's case titles name.

Every seed recipe is self-contained: it empties the database, provisions the tenant through the console
script a first deployment runs, declares the fixture over the HTTP API, and ticks the plan-horizon
maintainer. The suite loads its own fixture per file, so `just e2e` needs no seed run first.

**One intermittent failure runs through the whole harness, and it is a product defect rather than a flake in
a recipe.** A route that answers an operation identifier can answer one that `GET /operations/{id}` then
404s for, which is ticket 1575. Reached from all three routes that answer one, and measured by two people; the
planning figure is **one red run in five to ten full-suite runs**, and one occurrence ended a run after a
single case because the identifier was drawn during a fixture load. Ticket 1575 carries every sample. It is
never retried and never tolerated: the harness
reports it by name, so a run that draws it reads as the known defect rather than as a fault in whichever
case was running. Every seed recipe but one has never failed.

## What is mocked, and what is not

One thing: the external calendar provider, **at the network boundary**. `e2e/docker-compose.e2e.yml`
adds an HTTP server on the stack's own network serving the feeds in `e2e/fixtures/ics`, and a source
points at it the way a user points one at a university portal. The api's ICS path is unmodified and
unaware; the fetch is a real fetch over a real socket.

Nothing else is replaced. The database is a real Postgres, the migrations run as the one-shot a deploy
runs, the worker consumes the operation queue on its own five-second cadence, the debounce is the real
1.5 seconds, and the frontend is the built application served by Caddy on the one origin the deployed
stack serves.

**Google is not mocked, and it is not connected either.** The e2e stack blanks the Google credentials,
so the connect flow reports that Google is not configured and no Google code path runs. Mocking Google
would need TLS interception, because the API base is a module constant rather than a setting, and the
scenarios that turn on a real Google account are manual for that reason.

**The projection is computed and refused rather than written.** `GOOGLE_PROJECTION_WRITES` is false in
every environment: the destructive reconciliation has met the real Google API only from the marked live
suite against a development calendar, never from an armed deployment over a horizon of real plan
blocks. So the projection pass runs in full and stops before any request is sent; S3 is the scenario
that observes an event arriving on a device.

## The clock, and why no scenario names a fixed week

The plan-horizon maintainer plans `[today, today + horizon_days)`. A scenario naming 2026-W07 would
therefore observe an empty week the day after it was written. Every week a scenario or a fixture names
is derived from today, in the tenant's home zone:

| Name | Which week | Why |
|---|---|---|
| the plan week | next ISO week | Every day of it is in the future whatever weekday the suite runs on, and a 14-day horizon always covers the whole of it |
| the current week | the week today is in | The only week that holds days already lived, which is what a backfill and a passed deadline need |
| beyond the horizon | fifty weeks out | Far enough that no horizon setting reaches it |

A consequence, stated rather than worked around: a scenario about the past is bounded by how far into
the current week today is. S13 skips itself, with a message, when fewer than two days of this week have
been lived. The alternative would be manufacturing a past, and a fixture that invents days the product
never ran through is a fixture that proves nothing about the product.

## The fixtures

`just seed-<name>` for each. Five of these also exist as frozen values in `syncr_domain.fixtures`, read
by the domain and api suites. Their numbers are read out of those modules by
`e2e/harness/constants.py` rather than restated in the seed, so a fixture that stops straddling its own
gap breaks in one place instead of drifting in two.

| Fixture | Recipe | Contents |
|---|---|---|
| `reference_week` | `just seed-reference` | A frame span crossing midnight, a fifteen-minute compact block, an interview anchor with prep, transit and a recovery window, an anchor conflict, a queue binding, four Areas with floors, three tasks with deadlines, and three anchor types over two mocked feeds |
| `dst_weeks` | `just seed-dst-weeks` | A real zone, a Sunday-night frame span crossing the ISO week boundary, a travel override across the next transition. Prints both transition weeks: at most one is ever inside the horizon |
| `off_plan_week` | `just seed-off-plan-week` | A Friday-to-Monday off-plan span with `keepFrame` false |
| `elastic_sleep` | `just seed-elastic-sleep` | A sleep routine whose minimum is below its target, an inelastic routine beside it, and a deadline the week cannot meet |
| `partial_progress` | `just seed-partial-progress` | A task with a deadline and half its placements pinned, plus the week's already-ended blocks left unconfirmed |
| `recovery_scopes` | `just seed-recovery-scopes` | Two anchor types at the same wall time, one `post_scope: areas` forbidding Study and one `post_scope: all` |
| `shadow_geometry` | `just seed-shadow-geometry` | The `Interview`, `Exam` and `Lecture` types with their real leads, durations and buffers |
| `maturity_corpus` | `just seed-maturity-corpus` | Outcomes recorded on every block the weeks in the horizon have ended, and a print of what it reached. It carries a tolerance for one refusal, `past_disagreement` on a solve of the current week, **which no longer occurs**: measured, the current week and the two after it all solved and the tolerance branch was never taken. Making the seed refuse it rather than tolerate it is what closing ticket 1570 leaves behind |
| `tight_capacity` | `just seed-tight-capacity` | A week whose declared floors sit just inside its remaining capacity, and whose one deadline owes more before it than the week can hold: twenty and a half hours of frame a day, so 1470 discretionary minutes a week against 960 minutes of floor, and a 510-minute task due against the 420 minutes in front of its own deadline. The one fixture that makes a floor reservation observable, and its pre-deadline shortfall is exactly one 90-minute chunk, which is the task's own minimum chunk, so a single placement is the whole of it, before anything is solved or pinned. `elastic_sleep`'s plan week reports one too, 1200 minutes from an oversized demand against 6300 discretionary minutes rather than from a tight week, and `owes_more_than_a_week`'s reports 120 |
| `owes_more_than_a_week` | `just seed-owes-more-than-a-week` | One Area with no floor, no routine and no slot, so a week's discretionary time is its whole span, and two tasks sharing one deadline beyond the plan week that owe more than the longest week could hold. Its gap is therefore present at every instant of every week rather than only late in one, which is what makes the span a verdict measures capacity over assertable as a figure |

`hand_tuned_weights` is not a recipe: the bootstrap provisions weight set version 1 with
`origin = "hand-tuned"`, so it is a fact of every tenant this harness creates rather than a fixture it
loads. `hostile_ics` is not one either: it is a corpus of feed bodies the api's adapter suite reads, and
nothing in a browser can observe a parse.

## The three whole-product paths

`e2e/tests/paths.spec.ts`. Automated.

| Path | What it crosses |
|---|---|
| pin to projection | the pin, its counterfactual, the debounce, the solve, the authority rule, the pending slot, the approval's version bump, and the projection operation |
| conflict resolution | a feed fetched over a real socket, ingest, detection on the solve's commit path, and the recorded answer |
| confirm and backfill | the ledger, the outstanding count, a range confirmation, and what a backfilled day counts as |

## The 37

| # | What it observes | Status | Where |
|---|---|---|---|
| S1 | A week materializes automatically; a week fifty weeks out states the horizon, offers two actions, and triggers no solve | automated | `s01-materialization.spec.ts` |
| S2 | Anchors, prep, transit and recovery from a real ICS source, with a real sync count | manual with a seed | `just seed-reference`, then Settings → the two sources |
| S3 | The plan reaches the phone: `Leave for Uni` and the prep present, the recovery window absent, a hand-created event removed | manual | needs a real Google account and `GOOGLE_PROJECTION_WRITES` |
| S4 | Late binding: a Career slot binds to the most urgent task and the reason names the selection | manual with a seed | `just seed-reference`, then solve the plan week |
| S5 | Pin and reflow: the block does not follow the cursor, one redraw on drop, the verdict on the same redraw | **not automated** | see "What this harness does not yet reach" |
| S6 | The counterfactual: `pinned`, `instead of`, and `cost` on the reason panel | manual with a seed | the pin path asserts the stored counterfactual; the panel is read by eye |
| S7 | Live infeasibility with a stable panel height | automated | `s7-verdict-panel-height.spec.ts`: after each of three pins over the solved `tight_capacity` week it measures the panel's `boundingBox().height`, asserts the four readings equal, and asserts the row count changed across the same sequence; shown to fail with `height: var(--verdict-h)` removed from `.verdict-panel`. The verdict half remains covered by S9 and by the B1 case in `b1-s34-floors-and-unallocated.spec.ts` |
| S8 | Provenance strengthens from a capacity check to an authoritative reading | manual with a seed | `just seed-elastic-sleep` |
| S9 | A tradeoff is a proposal; an approved one survives; **and the shortfall it quoted `delta_minutes` against has closed by at least that much** | automated | `s09-s11-s31-tradeoffs.spec.ts` |
| S10 | Twelve pins cost one solve, zero live revisions, zero calendar writes, at most one supersession | automated | `s10-burst.spec.ts`, asserting the single-flight invariant DURING the burst rather than after it |
| S11 | Supersession names its successor and surfaces as no failure | automated | `s09-s11-s31-tradeoffs.spec.ts` |
| S12 | Only conflicts notify | partly automated | the raise over the network and the recorded answer are in `paths.spec.ts`; the inline oxide rule, the persistent banner and the SSE push are not |
| S13 | Confirm and backfill: unconfirmed days are excluded, and backfilling brings them in | automated | `paths.spec.ts` |
| S14 | The cursor is derived: a confirmation advances it, a skip does not, a correction re-derives | manual with a seed | `just seed-reference` |
| S15 | Debt caps, and the miss at the cap is forgiven | manual with a seed | `just seed-reference` |
| S16 | Off-plan: nothing inside, a hatched band, the denominator, the streak, and a pin honoured | manual with a seed | `just seed-off-plan-week` |
| S17 | An unfillable slot's label opens prefilled capture, producing a soft preference and no pin | automated, and the capture flow **currently red by declaration** | `s01-materialization.spec.ts` asserts the `no_eligible_content` rendering: a solved week's Fitness and Career slots have no eligible content, so each stays at its declared time and names its Area. `s17-capture-from-an-unfillable-slot.spec.ts` drives the flow behind the label: its first case asserts that a label the grid draws as a control takes the pointer while the band holding it still refuses one; its second drives activation, the prefill and the confirm, and is marked as expected to fail, so the day the flow exists the suite goes red for passing unexpectedly and the marker has to be removed. Four things it waits on, each measured: the label an empty slot's band does not carry (ticket 1350), the reader of the capture URL and the task-addressed preference write (ticket 1490), and the grid canvas that grows until layout stops, which refuses a press on anything it has pushed out of a pointer's reach |
| S18 | Travel and DST: the frame moves, anchors stay, the axis is proportional | manual with a seed | `just seed-dst-weeks` |
| S19 | Write-target expiry: a banner, a Settings panel, and one reconnect action | manual | needs a real Google token to revoke |
| S20 | The CLI is an API: stable schemas, no prompt when piped, idempotent mutations, exit 9 and 8 | manual, partly automated | `cli/tests/test_every_command.py`; driving every command against a running API is ticket 1520, which this harness is the home for |
| S21 | Keyboard only, including a sliver-tier block | partly automated | `s21-keyboard-and-focus.spec.ts` drives the whole session on the keyboard, and every step is asserted as a TRANSITION rather than as a presence: `g w` by URL, `j` by the tier focus lands on across every tier the grid renders, `Shift+Down` by the pin read back over the api, `n` by the value the caret typed, `c` by the confirm request the key sends and by `confirmedAt` moving off null, `Shift+A` by the approval request it sends and the answer it got. Each key was shown to fail with its own press removed. The SLIVER TIER is not reached: no seeded week holds a block short enough to fall under 13px at any available zoom, so the 8-to-13px case is asserted against the real component by role in `frontend/src/ui/domain/week-grid/__tests__/block.test.tsx`. Ticket 1561 |
| S22 | Nothing spins: no spinner, no skeleton, no progress bar, no transition | automated | `s22-no-motion.spec.ts`, over the computed style of every element on eleven routes: every one of the shell's seven, both weekly-session modes, a week beyond the horizon, and a route that does not exist; and both amber notice surfaces the session can draw -- the raised panel on the plan week's session, and the promotion panel measured from rendered geometry on the session whose window holds the fixture's three weeks of pins |
| S23 | The restore drill | manual | `just drill-local` and `just restore-drill`, ticket 58 |
| S24 | A week materializes with no solver: every slot drawn as `not_solved`, every block carrying a reason | partly automated | `s01-materialization.spec.ts` asserts the `not_solved` rendering, which is the deliberate opposite of S17's, and the materialized revision. Disabling the solver's binding and search phases is not driven from here |
| S25 | Progress does not manufacture a shortfall | automated | `s25-progress-does-not-manufacture-a-shortfall.spec.ts`, driving the three-pin sequence on the tight-capacity week: pinning two hours of the deadline task leaves the gap at its exact figure, pinning unrelated work into the window grows it by exactly the minutes that land there, and a Fitness pin drops the solver's remaining floor work by exactly the pinned minutes while the probe's own reservation stays at zero |
| S26 | Sleep is negotiable, never silently | manual with a seed | `just seed-elastic-sleep`: the `reduce_routine` offer for Sleep and for no other routine is visible on the verdict |
| S27 | Preferences are authorable and honoured | manual with a seed | `just seed-reference` |
| S28 | Identity survives a re-solve | automated, and shown to fail | `s28-s37-identity.spec.ts`, over the candidate the re-solve produced rather than the live plan it did not change. Keying a habit's occurrence on the clock turns it red |
| S29 | The calendar does not go blank at the week boundary | **not automated** | needs the clock to cross a Sunday, which this harness does not move |
| S30 | Approving during a solve supersedes rather than adopting | automated, with a stated narrowing | `s30-s35-approval-and-verdict-events.spec.ts`: the invariant is asserted over the stamped input version. The interleaving where the solve is already RUNNING is not reachable from outside the worker and is covered in `packages/syncr-api/tests/test_approval_during_a_solve.py` |
| S31 | A tradeoff gets its own operation | automated | `s09-s11-s31-tradeoffs.spec.ts` |
| S32 | Recovery scope behaves as declared | manual with a seed | `just seed-recovery-scopes` |
| S33 | Prep and transit land where the settled records say | manual with a seed | `just seed-shadow-geometry`, observed at the API level and by eye |
| S34 | `Unallocated` is honest | automated **and currently red by declaration** | `b1-s34-floors-and-unallocated.spec.ts`. The strip's discretionary denominator is the whole week's span, so the figure is wrong; tracking ticket 1310. The case is marked as expected to fail, so the day the figure is supplied the suite goes red for passing unexpectedly and the marker has to be removed |
| S35 | Verdict transitions recorded exactly once, reads write nothing, the ratio is a number | automated, with a stated narrowing | `s30-s35-approval-and-verdict-events.spec.ts`. Two reads and a no-op maintainer tick append nothing; no two consecutive rows agree on both the reading and its provenance; the ratio is read through the product's own `caught_early_over`. The **exactly 0.5** value needs an episode whose OPENING row is session-flagged. Two routes read `X-Syncr-Session-Mode`, the pin and the tradeoff request, and neither of them is a mutation that flips a roomy week's reading, so the episode this suite can open is unflagged: ticket 1571 |
| S36 | The verdict cannot be gamed and it notices the clock | **partly automated** | `s36-verdict-and-the-clock.spec.ts` drives the two halves that need no clock MOVED, on `owes_more_than_a_week`: a verdict read on a week the clock has reached counts capacity from the reading instant onward, asserted as a figure against the same demand on the week ahead of it, which counts its whole span; and the denominator keeps the whole week in both. A skip then raises the gap by exactly the minutes the block held and returns none of its span to capacity. What remains is the third observation, advancing the clock past a deadline with work remaining, and one narrowing the file states in place: the block a skip is asserted on lies ahead of the reading instant, because the solver's gaps are clipped to it and a pin is refused into the past, so no block behind it is reachable without the clock |
| S37 | A re-solve does not shrink the work | automated | `s28-s37-identity.spec.ts`, measured over the plan the candidate becomes once approved |

Plus three cases that are not among the 37. B1 is the observation `reviews/spec-review-5.md` B1 requires;
the `no_eligible_content` case above is S17's reason half; and the refused tradeoff is the bound that
keeps S9's solve-first requirement a product rule rather than a test workaround: on the week a new user
actually has, materialized and unsolved, the request is refused and nothing changes.

| Case | What it observes | Status | Where |
|---|---|---|---|
| Refused tradeoff | A tradeoff requested honestly (a kind the verdict really enumerates) on a materialized, unsolved week answers `409`, names the solve the caller is missing, and leaves the shortfall and the revision history unchanged; solved, the same week offers the same kind and accepts it. Shown to fail where the guard is absent: there the same request answers 202 and its operation succeeds | automated | `refused-tradeoff.spec.ts` |
| B1 | A solved week whose floors are met by unpinned solver-placed blocks reports no `floors_exceed_capacity` and no inflated at-risk column; and pinning an already-placed block leaves the verdict unchanged | automated, and shown to fail | `b1-s34-floors-and-unallocated.spec.ts`, on the `tight_capacity` fixture. Reverting the probe's floor reservation to the pre-B1 immovable-only rule turns two of its three cases red. `b1-at-risk-in-the-browser.spec.ts` drives the at-risk half's rendering in a browser: the mark on the row, the words behind it, the band's figure, and the narrowing the screen's own filter select asks the api for |

## Two corrections to section 22's done-criteria table

Recorded here because a traceability matrix built from that table mis-files three items. Both are note
4 of `reviews/spec-review-5.md`.

- **"Approving during a running solve cannot lose either outcome"** cites S30 and `US-PLAN-07`.
  `US-PLAN-07` is "read a week's revision history" and verifies nothing about an approval. The
  behaviour S30 exercises is covered by `US-SOLVE-03`'s version guard plus `US-PLAN-04`'s approval,
  and by `V3` and `PP6` in section 07.
- **"A degraded plan still explains itself"** cites S24 and S32, and `US-SOLVE-10` and `US-SOLVE-11`.
  S32 is about recovery scope and `US-SOLVE-11` is about a re-solve not shrinking the work; neither is
  about a degraded plan. The criterion is verified by **S24 plus `US-SOLVE-10`**.

## What this harness does not yet reach

Stated plainly, because an overstated bound is worse than a stated gap.

**One of these rows has been closed by giving the week its sequence.** The shortfall S25 needs a
pin to move is on `tight_capacity`, and `s25-progress-does-not-manufacture-a-shortfall.spec.ts`
now drives the three-step sequence against it: counted work pinned never moves the gap, unrelated
work pinned into the window moves it by exactly what lands, and a Fitness pin moves the floor
figures the way the two netting rules say it must. What is still missing from that pairing is only
the exactly-0.5 ratio's half: a verdict-flipping mutation through a route that carries the session
header, which ticket 1571 owns.

| Gap | Why | Where it should land |
|---|---|---|
| S5 | Needs a driven interaction on the week grid: a discrete drag with a real `setPointerCapture`. The harness has the browser and the credential; what is missing is the per-screen driving | ticket 1572 |
| S21's sliver tier | The session is driven on the keyboard, and every tier the grid RENDERS is reached; no seeded week holds a block short enough to render between 8 and 13px, so the tier the scenario names is exercised at the component level only | ticket 1561 |
| S17's capture flow | Driven now, and expected to fail: the label an empty slot's band does not carry, the reader of the capture URL the week screen writes, the task-addressed preference write, and a grid canvas sized from the height of the element containing it, which refuses a press on anything it has pushed out of a pointer's reach | `s17-capture-from-an-unfillable-slot.spec.ts`, tickets 1350 and 1490 |
| The exactly-0.5 early-catch ratio | Needs a mutation that flips a verdict through a route that carries the session header; the three-step sequence this row used to share its cell with is automated in `s25-progress-does-not-manufacture-a-shortfall.spec.ts` | ticket 1572 |
| S29 | Needs the clock moved across a Sunday-to-Monday boundary. Nothing in the stack takes an injected clock from outside the process | ticket 1573 |
| S36's third observation, and its skip half's one narrowing | Advancing the clock past a deadline with work remaining needs the injected clock. The skip half is driven, on a block ahead of the reading instant: the solver's gap set is clipped to that instant and every placement lands on the grid at or after it, and a pin is refused both for a block that has begun and for a start already gone, so no task block behind the clock is reachable from a fresh seed | ticket 1573 |
| A first solve of a week already partly lived | **Reached, and no longer refused.** `just seed-maturity-corpus` solved the current week and the two after it, and the seed's tolerance of `past_disagreement` was never taken: a slot the week has already reached is left unbound, so a candidate for a lived week no longer restates that week's past. What is NOT reached is the tolerance itself. Nothing here fails if the refusal returns, because the seed still collects it and prints it as expected. A re-solve that drops or moves a started solver-placed block is still refused, which is the state that failure code exists for | ticket 1570 |
| The promotion panel's composed layout | **Reached.** `repeated_pins` explicitly solves three weeks past the plan week and pins Wednesday's Dinner to 19:15 in each, which materialization alone cannot reach: a pin is refused on a block that has begun, so a 14-day horizon never holds three pinnable weeks whatever weekday the suite runs on. `s22-no-motion.spec.ts` asserts the session payload names the candidate before any pixel is read, then measures the table's box inside the notice surface's box, with the candidate's own row inside both, from `boundingBox()` readings rather than a class list. Shown to fail with the table displaced out of the panel, with a table rendering no rows, and with pins that move nothing. The raised-panel assertion is untouched and still bounds the other amber surface | `s22-no-motion.spec.ts` |
| One intermittent failure, anywhere an operation is awaited | A route that answers an operation identifier can answer one that `GET /operations/{id}` 404s for. Reached from all three such routes, at roughly one red run in five to ten. Not tolerated and not retried: `operation()` reports it by name | ticket 1575 |
| Google, and the deployed host | A real account, a real token to revoke, and a real systemd unit. Neither is a mock this suite could add honestly | S2, S3, S19, S23 |
