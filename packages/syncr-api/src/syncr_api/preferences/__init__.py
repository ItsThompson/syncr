"""The preferences module: the sole authoring path for a placement window.

One entity with a polymorphic owner, three route triples, and one resolution. Nothing here is
reachable from the areas, habits, or backlog modules: a preference is authored through the
owner's own sub-resource, and this package is what mounts those.

The rules the entity carries live in :mod:`syncr_domain.preferences`, so the table's check
constraints, the wire shapes' bounds, and the boundary's refusals are three readings of one
statement rather than three statements.

Two things a reader looking for them will not find here.

**No merge.** The routes are ``PUT``, not ``PATCH``: an override replaces its Area's windows and
ideal duration wholly, so there is no partial update to offer and no merge rule to express.

**No cap on an override.** ``maxPerDayMinutes`` is a field of the Area request shape and of no
other, so an override that could relax a hard cap is not a request this application can parse.
"""
