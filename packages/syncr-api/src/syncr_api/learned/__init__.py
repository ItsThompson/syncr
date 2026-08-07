"""The read and activation side of the learning layer: versioned weight sets and their maturity.

The fitters themselves live in ``syncr-learning``, which is offline and never imported by a request
path. This package holds the row they write, the row the solve path reads, and the three routes the
Learned screen and a revert address.

**Every module in this package appears in the table below**, which a test asserts against the
directory.

| Module | Holds |
|---|---|
| ``config.py`` | the vocabulary, the hand-tuned numbers P0 ships, and the three paths |
| ``models.py`` | the ``weight_sets`` table, and the partial index behind one active version |
| ``records.py`` | the frozen view the repository returns |
| ``repository.py`` | seeding version 1, reading the active one, listing the versions |
| ``activation.py`` | the flag flip, and the re-solve of FUTURE weeks that follows it |
| ``weight_reading.py`` | a stored row as the value the objective applies. One direction |
| ``maturity.py`` | the maturity array the nightly job wrote, read back into rows |
| ``gate_statements.py`` | the two claims the screen makes in prose, served beside the figures |
| ``views.py`` | the three shapes the service computes |
| ``service.py`` | ``LearnedService``: the read, the version list, and the activation |
| ``schemas.py`` | the wire shapes the three routes answer with |
| ``api.py`` | the three routes, each calling one service method |
| ``injection.py`` | the one place the service's collaborators are composed |
| ``wiring.py`` | the two prefixes, the tag, the origin check, and the statuses |
"""
