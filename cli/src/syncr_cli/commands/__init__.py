"""One module per noun, each registering its verbs in the catalog.

A command reads its arguments, calls one collaborator per thing it needs, and answers with a
:class:`~syncr_cli.results.CliResult`. It renders nothing and exits nothing: the runner does both,
which is what stops two commands laying out one verdict differently.

Every module in this package appears in the table below.

| Module | Holds |
|---|---|
| ``auth.py`` | ``auth login``, ``auth logout``, ``auth status`` |
| ``week.py`` | ``week show`` |
"""
