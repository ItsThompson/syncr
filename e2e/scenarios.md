# Which scenario each spec drives

One row per `*.spec.ts` in `tests/`, and the numbered smoke scenarios that file's cases name.

**The file name is not the statement, which is why this table exists.** Three of the files below drive
scenarios their own names do not carry: `s01-materialization.spec.ts` drives S17's and S24's slot
renderings as well as S1's, `paths.spec.ts` names no number at all, and two files carry an observation
that has no number to name. A reader looking for where a scenario is driven can follow
`docs/smoke-scenarios.md`, which maps each of the 37 to the file that drives it; what that table cannot
say anything about is a spec file driving none of them, because it has no row to hang it on.

**The first two columns are checked against the suite rather than trusted.** `npm run lint:spec-scenarios`
crosses them in both directions: every spec file on disk has exactly one row here, every row names a file
that exists, every file holds at least one case Playwright would run, and the numbers a row states are
exactly the numbers that file's case titles name. The titles come from `playwright test --list` rather
than from a regex over the source, so a commented-out case counts as nothing and a skipped one counts as
what it is. The third column is prose and nothing reads it.

`none` is a legitimate entry. A case that drives an observation outside the 37 is still a case, and a
statement that could only describe numbered work would leave the two files below unaccounted for.

| Spec                                          | Scenarios    | What it drives                                                                                                                                                                                                                  |
| --------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `b1-at-risk-in-the-browser.spec.ts`           | none         | The backlog's at-risk rows in a browser: the mark on the row, the words behind it, the band's figure, and the narrowing the screen's own filter select asks the api for                                                         |
| `b1-s34-floors-and-unallocated.spec.ts`       | S34          | A solved week whose floors are met by unpinned blocks; the at-risk column as set equality against the verdict that determines it; a pin that may not improve a verdict; and the unallocated figure, which is red by declaration |
| `paths.spec.ts`                               | S12, S13     | The three whole-product paths: pin to projection, conflict resolution, and confirm with backfill                                                                                                                                |
| `s01-materialization.spec.ts`                 | S1, S17, S24 | Automatic materialization, the stated empty state beyond the horizon, and the two slot renderings a degraded week and an unfillable slot draw                                                                                   |
| `s09-s11-s31-tradeoffs.spec.ts`               | S9, S11, S31 | A tradeoff as a proposal, the shortfall an approved one closes, the operation it gets of its own, and supersession naming its successor                                                                                         |
| `s10-burst.spec.ts`                           | S10          | Twelve pins in a burst, with the single-flight invariant asserted while the burst is running rather than after it                                                                                                               |
| `s17-capture-from-an-unfillable-slot.spec.ts` | S17          | A gutter label that takes the pointer inside a band that refuses one, and the capture flow behind it, which is red by declaration                                                                                               |
| `s21-keyboard-and-focus.spec.ts`              | S21          | A whole session driven on the keyboard, every key asserted as a transition rather than as a presence                                                                                                                            |
| `s22-no-motion.spec.ts`                       | S22          | Every element on eleven routes, over its computed style: nothing spins, and nothing transitions                                                                                                                                 |
| `s28-s37-identity.spec.ts`                    | S28, S37     | Block identity across a re-solve, over the candidate it produced, and a re-solve that does not shrink the work                                                                                                                  |
| `s30-s35-approval-and-verdict-events.spec.ts` | S30, S35     | Approving during a solve, and the verdict-transition ledger with the early-catch ratio the product's own rule reads                                                                                                             |
| `s36-verdict-and-the-clock.spec.ts`           | S36          | The two halves of the verdict's clock sensitivity that need no clock moved: capacity counted from the reading instant, and a skip that returns none of its span                                                                 |
