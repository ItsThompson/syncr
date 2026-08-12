"""Approving the pending proposal: one action, one transaction, and a version bump.

The whole feature is one act on one week, and it is a package of its own for the reason the pin
routes are: the week collection is served by several modules, and an act with its own refusals,
its own idempotency rule and its own transaction is easier to read beside them than inside the
composed read.

| Module | Holds |
|---|---|
| ``config.py`` | the path, the route name, and the resource word a refusal names |
| ``service.py`` | ``ApprovalService``: the refusals, and the one transaction |
| ``schemas.py`` | the wire shape one approval answers with |
| ``api.py`` | the one route, which demands an idempotency key |
| ``injection.py`` | the one place its collaborators are composed |
| ``wiring.py`` | the prefix, the tag, the origin check, and the statuses it answers |

The rule the transaction is stated over is that approving a proposal appends the revision, persists
any candidate adjustment, bumps the week's input version and clears the pending slot, all together.
That is also the reason it is one transaction: a partial approval would leave the slot holding a
proposal whose document is already the plan of record, and approving it again would append a second
revision of it.

The rule the transaction is SERIALIZED by is the week's version row, taken before anything is read.
The refusal is decided from the live plan, so the live plan has to be held while it is decided
against: ``service.py`` says which paths that keeps out, why one lock reaches all of them, and which
mechanism holds for a week whose version row does not exist yet.
"""
