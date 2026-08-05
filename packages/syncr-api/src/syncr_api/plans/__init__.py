"""The plan-storage package: revisions, the pending slot, the version row, and the facts.

Import layout, so a reader knows where to look. **Every module in this package appears in one of
the two tables below**, which a test asserts against the directory: this index was found twelve
modules stale once already, and an index a reader cannot trust is worse than none. Storage first:

| Module | Holds |
|---|---|
| ``config.py`` | the closed vocabularies, the table names, and the column bounds |
| ``models.py`` | the storage split's three tables |
| ``facts.py`` | the six permanent week-scoped tables, none of them ever pruned |
| ``derivation.py`` | the document-derived columns, computed in one place |
| ``records.py`` | the frozen views the repositories return |
| ``repository.py`` | ``PlanRepository``: append and reads, and no other write path |
| ``proposals.py`` | the single pending slot, replaced by upsert |
| ``versions.py`` | the input-version counter and the conditional-write guard |
| ``adjustments.py`` | approved tradeoff concessions, one per kind and target |
| ``errors.py`` | the two rejections a plan write raises, neither of them a caller's fault |

And the week assembler, which turns everything above plus every declaration a tenant holds into
one resolved ``SolveInputs``:

| Module | Holds |
|---|---|
| ``assembler.py`` | the one method: the pipeline, the stamped instant, the counts, the metric |
| ``injection.py`` | the one place its collaborators are composed |
| ``placements.py`` | the seam supplying the live plan and the pins |
| ``netting.py`` | the two placement sets, and every minute count taken over them |
| ``materialization.py`` | a declared wall time to instants per date, and what suppresses one |
| ``overhang.py`` | the preceding week's occurrences, as the time they occupy in this one |
| ``cadence.py`` | a habit's cadence to occurrences, with the cursor and the debt figure |
| ``multipliers.py`` | the learned duration multiplier, its maturity gate, its two applications |
| ``demand.py`` | the two TASK quantities, side by side |
| ``reservations.py`` | the two FLOOR quantities, the gross target, and the daily cap |
| ``resolved_preferences.py`` | the override chain, and the declared windows out to instants |
| ``calendar_occupancy.py`` | what a week's commitments occupy, and what their types cast in it |
| ``folding.py`` | the concession post-pass: one code path, four kinds |
| ``verdicts.py`` | the live verdict on the request path, and the caller-labeled histogram |
"""
