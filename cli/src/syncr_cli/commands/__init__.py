"""One module per noun, each registering its verbs in the catalog.

A command reads its arguments, calls one collaborator per thing it needs, and answers with a
:class:`~syncr_cli.results.CliResult`. It renders nothing and exits nothing: the runner does both,
which is what stops two commands laying out one verdict differently.

Every module in this package appears in the table below.

| Module | Holds |
|---|---|
| ``auth.py`` | ``auth login``, ``auth logout``, ``auth status`` |
| ``task.py`` | ``task add``, ``task list``, ``task done`` |
| ``backlog.py`` | ``backlog list`` |
| ``week.py`` | ``week show``, and the one composition of a week's ledger three commands read |
| ``plan.py`` | ``plan show``, ``plan solve``, ``plan approve`` |
| ``block.py`` | ``block done``, ``block skip``, ``block partial``, ``block move`` |
| ``day.py`` | ``day confirm`` |
"""
