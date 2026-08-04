"""Anchors and anchor types: imported commitments, and the shadows they cast.

An **anchor** is a fact. It is one commitment a calendar the user does not own published, and
syncr's whole relationship with it is read-only: no route edits one, no route deletes one, and
the only column a request may change is which type it carries. That is the boundary this package
is built around, because the source of truth for a lecture belongs to the university.

The anchor contract, stated once so the packages that read anchors do not each infer it:

*What is an anchor anchored to?* A ``(source_id, external_uid)`` pair, and nothing else. The
source is the calendar that published it and the UID is the identity that calendar gave it.
Neither its title nor its time is part of its identity.

*What if its source is removed?* The anchor goes with it, by the foreign key. A source's anchors
are its contribution, so removing a feed removes the occupancy it contributed.

*What if it moves at the source?* The same anchor is updated. A lecture moved by an hour is the
same commitment at a new time, so nothing is created and nothing is removed.

*What if it disappears at the source?* It is removed, but only after a **successful** read. A
failed sync marks it ``possibly_stale`` and keeps it: a feed being down is not evidence that a
lecture was cancelled.

*May two anchors occupy the same instant?* Yes, and nothing here prevents it. Two calendars can
each publish the same meeting, and two genuine commitments can genuinely overlap. Overlap is a
**plan** question, answered by the constraint checker and the conflict detector rather than at
ingest.

*Is it snapped to the quarter hour?* No. An anchor keeps its real time, even at ``:07``, and so
does every buffer derived from it.

*What does an untyped anchor cast?* Nothing at all. It is opaque busy time, and syncr makes no
assumption about it.

An **anchor type** is a declaration. It carries an ordered match rule and the full specification
of the shadow every anchor of it casts: a prep lead and duration, a transit lead and duration per
leg, a return leg, a recovery buffer, and what that recovery forbids. Rules evaluate in order and
the first match wins; a user's retype outranks every rule and persists on the series, so a daily
standup is typed once rather than 250 times.

**Where a span comes from.** ``shadows.py`` DERIVES the spans a commitment casts, from its own
interval plus the two leads and four durations its type declares. ``shadow_collisions.py`` NARROWS
one that an earlier-kept block already covers, ``shadow_products.py`` UNIONS them into the
interval sets a reader subtracts, and ``reach.py`` WIDENS a caller's own span into the one holding
every commitment that can cast a product inside it. **Those four are the only modules here that
compute time nobody stored.** The two others that name an interval at all merely rebuild one they
were handed: ``queries.py`` from the bounds a request asked to read, and ``repository.py`` from the
two columns a row holds. What the rest own is the declaration, the boundary rules the declaration
has to satisfy, and the reconciliation that decides which anchors exist and which type each one
carries. Every span the three shadow modules produce is unclipped, because which of them fall
inside a week is a question only the caller holding that week's span can answer.

Import layout, so a reader knows where to look:

| Module | Holds |
|---|---|
| ``config.py`` | the two closed vocabularies, the bounds, tables, route paths |
| ``models.py`` | the two tables, and the boundary rules as check constraints |
| ``records.py`` | the frozen views, the shadow specification, what a type declares |
| ``identity.py`` | bounding a publisher's values without merging two commitments |
| ``matching.py`` | first match wins, and the series override that outranks it |
| ``rules.py`` | what a declaration must satisfy, and the reason each rejection states |
| ``shadows.py`` | the arithmetic: one anchor plus its type into blocks and windows |
| ``shadow_products.py`` | what that arithmetic produces, and the questions asked of it |
| ``shadow_collisions.py`` | which block survives when two commitments cast over each other |
| ``reach.py`` | how far a declaration casts, and the span a week's assembly must read |
| ``repository.py`` | scoped persistence for anchors, and the only writer of a fact |
| ``type_repository.py`` | scoped persistence for types, and rule order's lock |
| ``reconcile.py`` | one feed's events into the anchors a tenant holds |
| ``evaluation.py`` | re-applying the rules after the rule set changes |
| ``declarations.py`` | what a request asked to change, three-valued per field |
| ``views.py`` | the composed answers a route hands back |
| ``queries.py`` | reading a bounded span and an opaque page cursor |
| ``schemas.py`` | the wire shapes |
| ``service.py`` | authorization, ordering, and the solve-input bump |
| ``injection.py`` | the dependencies a route resolves per request |
| ``wiring.py`` | the router the application mounts |
| ``api.py`` | the seven routes |
"""
