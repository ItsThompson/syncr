"""The Postgres adapter: the whole of this job's I/O, and the one place its spellings are stated.

The api owns every table this reads. This package cannot import it, because the api image must not
carry scipy, so the job's I/O has to live here and the names have to be restated.
``tests/test_solver_agreement.py`` is what keeps the two copies from drifting.

**Every module in this package appears in the table below**, which a test asserts against the
directory.

| Module | Holds |
|---|---|
| ``spelling.py`` | every table, column and JSONB key this job names, as constants a test crosses |
| ``documents.py`` | a stored plan document and edit context to the values above them |
| ``reader.py`` | the corpus reader: four reads, each scoped to one tenant, none of them a write |
| ``writer.py`` | the one write: append a new weight-set version, never active, never an update |
| ``engine.py`` | the settings, the engine and the session factory a one-shot container builds |
"""
