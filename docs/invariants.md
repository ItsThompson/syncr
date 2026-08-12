# The invariant labels

The product's design numbers its invariants, and comments in this repository cite those numbers: `H9`, `VE8`, `PN3`. This file is the only place in the repository that says what each one requires. Without it a label is a pointer to nothing, so a maintainer who meets `H9` in a comment reads it here.

**A comment is better off stating the requirement than citing the number.** A number tells a reader to go and look something up; the sentence tells them what the code has to do. Use the sentences below when writing or rewriting a comment, and keep the label only where the number itself is what a reader needs.

The families:

- `H`: the hard constraints, which say what the solver may never place
- `O`: the outcome log, which records what happened to a block
- `OP`: off-plan spans, the periods a user declares themselves away from the plan
- `PN`: pins, the user's own placement of a block
- `PP`: the pending proposal a solve leaves behind for approval
- `R`: routines, the recurring frame that bounds a day
- `V`: the week's input version, which is how a solve knows its inputs moved under it
- `VE`: verdict events, the log of how a week's feasibility changed

Two numbers, `H5` and `H15`, name rules that were withdrawn. Their rows stay, and say so, because the numbering was never compacted and older references still resolve.

## What each label requires

| Label | What it requires |
|---|---|
| `H1` | The solver never places a block over an imported calendar commitment, which is an external fact the plan gives way to. |
| `H2` | The solver never places a block inside a window that forbids every Area, such as an absolute recovery window or a buffer whose type named no Area. |
| `H3` | The solver never places a block over a routine occurrence at the effective duration the week assembler clamped it to. |
| `H4` | The solver never creates an overlap between two blocks it places, though an overlap between facts the solve did not choose is kept rather than refused: a routine and its own next occurrence, two imported commitments, or a block the user pinned. |
| `H5` | A withdrawn rule number, kept so older references still resolve: nothing refuses a placement for sitting outside a preferred window, because a preference is a cost in the objective rather than a refusal. |
| `H6` | The solver never splits a block whose content is atomic, so it places the whole duration or none of it. |
| `H7` | The solver never places a piece of a splittable block shorter than the minimum chunk its content declares. |
| `H8` | The solver never lets one Area's placed minutes on one local date exceed the daily cap that Area declares. |
| `H9` | The solver never leaves an Area under a floor the week could still meet, and only an approved breach may go under it. |
| `H10` | The solver never moves a block that has started or is in the past, judged against the instant stamped on its inputs. |
| `H11` | The solver never moves a block the user pinned, or one fixed by derivation. |
| `H12` | The solver places nothing inside a declared off-plan span except a pin, which is already immovable to it. |
| `H13` | The solver never places a forbidden Area inside a recovery window scoped to named Areas, and leaves every other Area free there. |
| `H14` | Every start and end the solver places lands on the fifteen-minute grid, while an imported commitment and the buffers derived from it keep their real times. |
| `H15` | A withdrawn rule number, kept so older references still resolve: no solver operation resizes a routine, so clamping an occurrence to its minimum is the week assembler's validation instead. |
| `O1` | A block is presumed complete unless the user says otherwise, so the absence of an outcome row is the ordinary case rather than missing data. |
| `O2` | An outcome reporting partial completion carries the minutes actually spent, because that pair is the only source of the duration-estimate signal. |
| `O3` | A day the user never confirmed is excluded from reviews and from learning, so a day of disengagement is not recorded as a perfect one. |
| `O4` | Any past day can be confirmed at any later time, and a day confirmed late counts identically for the maturity gates. |
| `O5` | Correcting a past confirmation re-derives everything projected from the outcome log, including rotation cursors and outstanding debt. |
| `O7` | An outcome reporting that the block moved carries the interval it actually ran in, and it creates no pin. |
| `O8` | An outcome whose binding no longer exists is kept, because it is a fact about a week that already happened. |
| `OP1` | An off-plan span runs forward with both bounds on the fifteen-minute grid, and it is not restricted to whole days or weeks. |
| `OP2` | Two off-plan spans for one tenant never cover a common instant, and an overlapping declaration is refused with a stated reason. |
| `OP7` | An imported commitment overlapping a pinned block inside an off-plan span is still a conflict, with no special case for the span. |
| `OP8` | An off-plan span reduces discretionary time through the union of the intervals already spent, never by adding its own minutes to a total. |
| `PN1` | A pin constrains only the week it was made in, and the next week's solve is unconstrained by it. |
| `PN2` | The record of a pin lasts permanently even after its binding is released, because one is a live constraint on this week and the other a fact about a week that happened. |
| `PN3` | Every pin stores the placement it superseded and what replacing it cost the objective, permanently. |
| `PN4` | A pin's objective delta is stored and never recomputed later, because the weight set that produced it is versioned and will have moved on. |
| `PP3` | Approving a proposal appends the approved revision, persists any candidate adjustment, bumps the week's input version and clears the pending slot, all in one transaction. |
| `PP5` | A proposal may be approved while its input version is behind the week's current one, and the revision records the version it was solved against so the gap is visible rather than hidden. |
| `PP6` | The version bump on approval is what protects a solve running at the same time, because without it that solve's conditional write would still match and would commit a classification computed against a plan that no longer exists. |
| `R6` | The week assembler computes each routine occurrence's effective duration and clamps it to the routine's own minimum, which is a validation on the assembler rather than a rule the solver checks. |
| `V3` | Every mutation that affects a solve bumps the week's input version, including one that changes the live plan, so approving a proposal bumps it too. |
| `V5` | The input-version row is the single serialization point for anything that invalidates a running solve, which is why one guard covers both changed inputs and a changed live plan. |
| `VE1` | The verdict-event log is append-only, so a row is never updated and never pruned. |
| `VE2` | A verdict event is written only on a transition, meaning the week's first verdict or a change in feasibility or a change in provenance while infeasible, so a verdict recomputed identically writes nothing. |
| `VE3` | Whether the weekly session was open is supplied by the caller, because only the caller knows, and both the horizon maintainer and the CLI report false. |
| `VE4` | A probe transition to infeasible followed by a solver transition confirming it writes two rows belonging to one episode, which is what lets the metric tell a capacity warning from an authoritative finding. |
| `VE5` | A verdict transition is written in the same transaction as the request or job that computed it, and never in one of its own. |
| `VE6` | No read path writes a verdict event, so a read may compute a verdict to display and appends nothing. |
| `VE7` | The horizon maintainer evaluates every verdict in one tick against one instant, the same one it hands to the week assembler. |
| `VE8` | The horizon maintainer writes only on a change in feasibility and never on a change in provenance, and for it a week with no row at all reads as feasible. |
| `VE9` | An episode runs from a transition to infeasible until the next transition back to feasible for that week, and the episode's first row is the one that says whether it was caught while the weekly session was open. |

## How this file is kept total

`just lint` runs a census of the labels the repository cites and fails when one has no row here:

```
python3 tools/invariant_labels.py            # what the tree cites, per label and per tree
python3 tools/invariant_labels.py --check    # the gate: every cited label has a row, and no swept tree names one
```

The census reads the files in git's index whose comment spelling `tools/comments.py` declares, which covers source, the `justfile`, the compose files and `deployments/`. It reads comments and stand-alone strings only, so the solver's `ConstraintRule` vocabulary and a rule name a test fixture passes as a value are not citations. Documentation is not read: it explains labels rather than citing them, and this file names every one of them.

A row nothing cites is only reported, never failed, because these rows outlive the comments that pointed at them.

## And why a comment may no longer name one

The same gate fails when a comment names a label at all, because a comment is better off stating the requirement: the number tells a reader to go and look something up, and the sentence tells them what the code has to do. The trees whose comments still name labels are listed by name in `PENDING` in `tools/invariant_labels.py`, with the reason each is still true, and a listed tree that cites nothing fails too, so an entry cannot outlive the change that empties it.

Between the two the gate covers one set with no gap: every file the census reads either may not name a label, or is under a tree that says why it still does.
