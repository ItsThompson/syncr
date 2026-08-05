"""One result, written for a person or for an agent, from the same object.

Human output follows the product's own discipline: dense, mono, tabular figures, no ornament, no
color, and no progress output of any kind. A pipe strips color and a pipe does not strip a word,
so a conflict, a pin, and an origin are each named in words.

Every module in this package appears in the table below.

| Module | Holds |
|---|---|
| ``human.py`` | One result as the lines a terminal shows, in five groups |
| ``json_output.py`` | One result as the JSON an agent parses |
| ``ledger.py`` | The week ledger: its heading, its readings, and its day rows |
| ``day_rows.py`` | Which rows fall on which date, and how a row is spelled |
| ``durations.py`` | The three renderings of a duration, and which surface each belongs to |
| ``auth_views.py`` | What the three authorization commands answer with |
"""
