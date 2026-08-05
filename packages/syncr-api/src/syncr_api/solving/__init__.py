"""Solve orchestration: the ``Operation`` resource and its lifecycle.

| Module | Holds |
|---|---|
| ``config.py`` | the two vocabularies, the bounds, the retention windows, and the route paths |
| ``models.py`` | the ``operations`` table and its two load-bearing indexes |
| ``records.py`` | the frozen view the repository returns |
| ``transitions.py`` | the state machine: which steps exist, and which states are the end |
| ``outcomes.py`` | the three ways work ends, one value each |
| ``errors.py`` | the one rejection a step raises |
| ``reporting.py`` | what each status means to the user, one sentence per word |
| ``repository.py`` | the per-operation statements, each carrying its own legality |
| ``sweeps.py`` | the two set-wide statements maintenance runs |
| ``queue.py`` | what is waiting to be done, for the worker duty that drains it |
| ``lifecycle.py`` | create, claim, finish: the writes, and the one enforcement of the machine |
| ``service.py`` | the two reads a route answers with, on an explicit principal |
| ``maintenance.py`` | the worker duty: return the abandoned claims, prune the terminal rows |
| ``queries.py`` | the list route's two filters and its opaque page cursor |
| ``schemas.py`` | the wire shape a client follows an operation through |
| ``api.py`` | the two read routes |
| ``injection.py`` | the request-side wiring |
| ``wiring.py`` | the one factory the app factory calls |

The solve coordinator is deliberately absent. The single-flight invariant, the debounce window, the
conditional write, and the scan that decides WHICH due operation a worker claims are one component
with one invariant, and it builds on the lifecycle here rather than beside it.
"""
