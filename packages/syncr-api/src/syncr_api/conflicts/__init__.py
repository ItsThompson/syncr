"""The conflict surface: reading the overlaps nothing may settle quietly, and answering one.

A conflict is the only condition in this product that pushes a notification, so this package holds
what a user does about one. It holds no table: the record is plan storage's, in
``plans/conflicts.py``, and the detection is ``plans/overlaps.py``. What lives here is the act.

**Every module in this package appears in the table below**, which a test asserts against the
directory, because an index a reader cannot trust is worse than none.

| Module | Holds |
|---|---|
| ``config.py`` | the two paths, the resource name, and the fields a rejection cites |
| ``declarations.py`` | the answer a caller chose, as one value |
| ``overlapped.py`` | which block a conflict names, and who can move it |
| ``pins.py`` | the pin release the ``moved`` answer needs, declared where it is needed |
| ``ingest.py`` | detecting the overlaps a calendar sync just created, against the live plan |
| ``service.py`` | ``ConflictService``: the read, and what each of the three answers does |
| ``views.py`` | the pair a resolution answers with: the record, and the solve that reads it |
| ``schemas.py`` | the wire shapes the two routes read and answer with |
| ``api.py`` | the two routes, each calling one service method |
| ``injection.py`` | the one place the service's collaborators are composed |
| ``wiring.py`` | the prefix, the tag, the origin check, and the statuses they answer |
"""
