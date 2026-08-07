"""One result, written for a person or for an agent, from the same object.

Human output follows the product's own discipline: dense, mono, tabular figures, no ornament, no
color, and no progress output of any kind. A pipe strips color and a pipe does not strip a word,
so a conflict, a pin, and an origin are each named in words.

Every module in this package appears in the table below.

| Module | Holds |
|---|---|
| ``human.py`` | One result as the lines a terminal shows, in five groups |
| ``json_output.py`` | One result as the JSON an agent parses |
| ``views.py`` | What every payload with no week around it shares |
| ``ledger.py`` | The week ledger: its heading, its readings, and its day rows |
| ``day_rows.py`` | Which rows fall on which date, and how a row is spelled |
| ``day_views.py`` | One date's ledger, for ``plan show --date`` and ``day confirm`` |
| ``task_views.py`` | The backlog, a captured task, and a completed one |
| ``edit_views.py`` | What a recording, a move, and an approval answer with |
| ``solve_views.py`` | A requested solve, and what a wait settled on |
| ``durations.py`` | The three renderings of a duration, and which surface each belongs to |
| ``auth_views.py`` | What the three authorization commands answer with |
"""
