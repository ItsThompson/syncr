"""The plan-storage package: revisions, the pending slot, the version row, and the facts.

Import layout, so a reader knows where to look:

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
"""
