"""The pin package: the user's own edits, and the training labels they are.

| Module | Holds |
|---|---|
| ``config.py`` | the three paths under one week, the route names, and the field a refusal names |
| ``declarations.py`` | what a caller asks for: a block and a start, or a block alone |
| ``features.py`` | the feature snapshot one edit is recorded with, derived and pure |
| ``costs.py`` | what the user's choice cost, from two evaluations of one objective |
| ``schemas.py`` | the two request bodies, the pin, and the three-field answer |
| ``service.py`` | the three acts: pin, reject, release |
| ``release.py`` | the pin release the conflict path reaches through |
| ``api.py`` | the three routes, each calling one service method |
| ``injection.py`` | the one place its collaborators are composed, scoped to a tenant |
| ``wiring.py`` | the router the app factory asks for |

**A pin is two things and this package writes both.** It is the constraint this week's solve may not
move, which is the ``pins`` row, and it is a pairwise preference in a known context, which is the
``edit_events`` row written in the same transaction. The second is why the first cannot be written
alone: a pin without its features is a training label the learning layer can never use, and the
features are a fact about an instant that has passed.

**The tables are the plan package's** (:mod:`syncr_api.plans.pins`, :mod:`syncr_api.plans.edits`),
because that package owns plan storage, which is the same split the conflict and concession packages
already take. What lives here is the write path, the arithmetic, and the routes.

**Nothing here creates a pin as a convenience.** Every path takes a block the caller named, and the
drag rules that stop a jittery pointer from naming one are the Week screen's own.
"""
