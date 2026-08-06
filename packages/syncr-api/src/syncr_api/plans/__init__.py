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
| ``conflicts.py`` | the conflict record: raised once per commitment and block, and retained |
| ``adoption.py`` | the writes a classification names: the live plan, the slot, or nothing |
| ``versions.py`` | the input-version counter and the conditional-write guard |
| ``adjustments.py`` | approved tradeoff concessions, one per kind and target |
| ``pins.py`` | ``PinRepository``: the live constraint a pin is, held, priced and released |
| ``edits.py`` | ``EditEventRepository``: the training corpus, appended and never pruned |
| ``edit_context.py`` | the feature snapshot one edit carries, and what makes it a feature vector |
| ``declarations.py`` | what a caller states when it writes a pin and the event beside it |
| ``reality.py`` | the outcome log: one row per block, recorded and corrected in place |
| ``habit_log.py`` | the same log keyed by habit, for the rotation cursor and outstanding debt |
| ``errors.py`` | the six rejections a plan write or a plan read raises, none a caller's fault |
| ``stored_values.py`` | the leaf forms a stored document is built from: an instant, a span, an id |
| ``stored_clauses.py`` | the six reason clauses, one stored form each |
| ``stored_reasons.py`` | a block's reason record, and which of the six kinds a stored object is |
| ``stored_documents.py`` | a whole week, written from and rebuilt through the domain constructors |
| ``stored_proposals.py`` | the assent-requiring changes, in the form the pending slot holds |
| ``stored_verdicts.py`` | a verdict's stored form, written into the pending slot and read back |
| ``stored_contexts.py`` | an edit context's stored form, both directions, over one JSONB column |
| ``overlaps.py`` | the two overlaps nothing may settle quietly, detected against the live plan |
| ``settled.py`` | what the week has lived, and which of it a candidate may not restate |
| ``authority.py`` | the authority rule: what auto-applies, what waits, and what collides |

And the week assembler, which turns everything above plus every declaration a tenant holds into
one resolved ``SolveInputs``:

| Module | Holds |
|---|---|
| ``assembler.py`` | the one method: the pipeline, the stamped instant, the counts, the metric |
| ``injection.py`` | the one place its collaborators are composed |
| ``placements.py`` | the seam supplying what a week already holds, and which pins constrain |
| ``netting.py`` | the two placement sets, and every minute count taken over them |
| ``materialization.py`` | a declared wall time to instants per date, and what suppresses one |
| ``entry_content.py`` | what a concrete entry's block is called, and the Area it charges |
| ``overhang.py`` | the preceding week's occurrences, as the time they occupy in this one |
| ``cadence.py`` | a habit's cadence to occurrences, with the cursor and the debt figure |
| ``multipliers.py`` | the learned duration multiplier, its maturity gate, its two applications |
| ``demand.py`` | the two TASK quantities, side by side |
| ``reservations.py`` | the two FLOOR quantities, the gross target, and the daily cap |
| ``resolved_preferences.py`` | the override chain, and the declared windows out to instants |
| ``calendar_occupancy.py`` | what a week's commitments occupy, and what their types cast in it |
| ``folding.py`` | the concession post-pass: one code path, four kinds |
| ``readiness.py`` | the minimum inputs a week needs before a plan can exist for it |
| ``production.py`` | one week's declarations to one stored revision, and the two reasons for one |
| ``verdicts.py`` | the live verdict on the request path, and the caller-labeled histogram |
| ``tradeoffs.py`` | what could close each gap, what it recovers, and nothing chosen |
| ``tradeoff_nights.py`` | which nights a routine reduction touches, and by how much each |
| ``tradeoff_targets.py`` | which targets a gap names, per kind: the selection half |
| ``tradeoff_labels.py`` | the words a tradeoff is offered in, per kind |
| ``candidates.py`` | a candidate concession's path to the worker, and the reductions read |

And the week routes, which compose everything above into the Week screen's whole read:

| Module | Holds |
|---|---|
| ``week_config.py`` | the four paths and the resource name the week routes read |
| ``service.py`` | ``WeekService``: the composed read, the history, the verdict, and the solve |
| ``week_views.py`` | the two shapes it answers with, which the wire schemas describe |
| ``api.py`` | the four routes, each calling one service method |
| ``wiring.py`` | the prefix, the tag, the origin check, and the statuses they answer |
| ``emptiness.py`` | why a week holds no plan, and the facts the two actions need |
| ``readings.py`` | the eight figures the strip shows and the review divides |
| ``currency.py`` | how current a week's plan is, from the week's own operation state |
| ``confirmations.py`` | the seam answering which of a week's days the user has confirmed |
| ``schemas.py`` | the wire shapes the four routes answer with |
| ``document_schemas.py`` | a stored document on the wire: the blocks and the two kinds of gap |
| ``verdict_schemas.py`` | a verdict on the wire, and the weaker reading a probe verdict renders |
| ``clause_schemas.py`` | the six reason clauses on the wire, discriminated by kind |
"""
