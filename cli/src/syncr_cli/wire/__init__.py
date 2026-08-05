"""The payloads the api sends, read into shapes the renderings can print.

Reading is tolerant about what it does not need and strict about what it does: a member this
package renders is required and refused loudly when it is the wrong kind, and a member it does not
render is not read at all. The ``--json`` output carries the api's own object whatever this
package models, so a member no reader here names is never lost.

Every module in this package appears in the table below.

| Module | Holds |
|---|---|
| ``reading.py`` | Reading one member out of a payload, and saying where it was wrong |
| ``week.py`` | The composed week view and its readings |
| ``plan.py`` | The blocks a week holds, and the windows that explain its gaps |
| ``verdict.py`` | Whether a week can hold its commitments, and how that was decided |
| ``operation.py`` | The resource a long-running job is followed through |
"""
