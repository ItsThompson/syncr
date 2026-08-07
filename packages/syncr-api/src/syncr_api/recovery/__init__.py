"""Reading a restore back: the fingerprint the drill's verdict is stated over.

``syncr-plan-fingerprint`` writes one JSON document describing a database. It runs twice per drill,
against two different databases, in the same image, so what the drill compares is two readings by
one reader rather than two readers that could disagree.

It lives in the api package because the reading it takes is not one the deployment tooling can
produce: a row count is SQL, but the rotation cursor is a projection of the outcome log that
:mod:`syncr_domain.cursor` owns, and re-implementing it beside ``pg_dump`` would put a domain rule
in a second place and make the drill agree with itself while the product disagreed.
"""
