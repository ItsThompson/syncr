"""Idempotent unsafe requests: the key's storage, and the branch every retry takes.

An ``Idempotency-Key`` on an unsafe method is not optional politeness. An AI agent
retrying a ``POST`` must not create a second pin or a second task, and a browser that lost
a response has no way to know whether the write landed.

| Module | Holds |
|---|---|
| ``config.py`` | the header name, the retention window, the states, the column bounds |
| ``fingerprints.py`` | the request hash and the lock token, both pure |
| ``models.py`` | the ``idempotency_keys`` table |
| ``records.py`` | the frozen view the repository returns |
| ``repository.py`` | the five statements the branch is made of |
| ``guard.py`` | ``IdempotencyGuard.once``: the whole branch, behind one call |
| ``injection.py`` | the two dependencies a route declares |
"""
