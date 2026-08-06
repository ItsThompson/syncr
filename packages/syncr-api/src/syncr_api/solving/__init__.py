"""Solve orchestration: the ``Operation`` resource, its lifecycle, and the coordinator.

| Module | Holds |
|---|---|
| ``config.py`` | the vocabularies, the bounds, the windows, and the route paths |
| ``models.py`` | the ``operations`` table and its two load-bearing indexes |
| ``records.py`` | the frozen view the repository returns |
| ``transitions.py`` | the state machine: which steps exist, and which states are the end |
| ``outcomes.py`` | the three ways work ends, one value each |
| ``errors.py`` | what a refused step raises, and what a tradeoff meeting a running solve does |
| ``reporting.py`` | what each status means to the user, one sentence per word |
| ``failures.py`` | why a solve failed: the four causes, one sentence each |
| ``metrics.py`` | what the orchestration publishes about itself |
| ``repository.py`` | the per-operation statements, each carrying its own legality |
| ``sweeps.py`` | the two set-wide statements maintenance runs |
| ``queue.py`` | what is waiting to be done, for the worker duties that read it |
| ``lifecycle.py`` | create, claim, finish: the writes, and the one enforcement of the machine |
| ``coordinator.py`` | the single-flight invariant, the debounce window, and the claim scan |
| ``checkpoints.py`` | the cooperative checkpoint a running solve reads |
| ``snapshots.py`` | a failed solve's inputs, as the document its operation retains |
| ``dispatch.py`` | one claimed solve, from its inputs to the status it ends in |
| ``runner.py`` | the worker duty: claim every due solve and run it |
| ``service.py`` | the two reads a route answers with, on an explicit principal |
| ``maintenance.py`` | the worker duty: return the abandoned claims, prune the terminal rows |
| ``queries.py`` | the list route's two filters and its opaque page cursor |
| ``schemas.py`` | the wire shape a client follows an operation through |
| ``api.py`` | the two read routes |
| ``injection.py`` | the request-side wiring, and the coordinator's one factory |
| ``wiring.py`` | the one factory the app factory calls |

The coordinator builds ON the lifecycle rather than beside it: which steps exist and what makes one
atomic is ``transitions.py`` and ``lifecycle.py``, and what the coordinator adds is WHICH operation
is stepped and when.
"""
