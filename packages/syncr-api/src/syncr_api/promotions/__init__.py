"""Repeated-pin promotion, as a reader answers it: absorb the pattern, or silence it for a while.

The rule that FINDS a pattern is ``syncr_domain.promotion``, because two readers share it: the
nightly learning run reports the candidates it finds, and the weekly session raises them as a
question. This package is the answer half, and it is the only place the template changes because of
one.

**Nothing here stores a candidate.** Detection is one pass over pin rows and runs on every session
read, so the candidates are always as fresh as the pins behind them. The one thing that cannot be
recomputed is the reader's answer, which is why the only table here is the declines.

**Every module in this package appears in the table below**, which a test asserts against the
directory.

| Module | Holds |
|---|---|
| ``config.py`` | the two paths, the table's name, and how long a decline silences a pattern |
| ``absorption.py`` | which patterns a template can absorb, and the sentence for the rest |
| ``models.py`` | the ``promotion_declines`` table, and the one decline per pattern behind it |
| ``records.py`` | the frozen view the repository returns |
| ``repository.py`` | recording one decline, and reading which patterns are still silenced |
| ``queries.py`` | reading a candidate's identifier out of a path, and the 422 for a malformed one |
| ``service.py`` | ``PromotionService``: the accept that moves an entry, and the decline |
| ``statements.py`` | the two sentences a surface renders, composed here rather than on a client |
| ``schemas.py`` | the wire shapes the two routes answer with |
| ``api.py`` | the two routes, each calling one service method |
| ``injection.py`` | the one place the service's collaborators are composed |
| ``wiring.py`` | the prefix, the tag, the origin check, and the statuses |
"""
