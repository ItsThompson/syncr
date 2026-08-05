"""Reality state: what happened to each block, and which days the user has answered for.

Blocks are **presumed complete** unless the user says otherwise, which is what keeps daily
interaction cost near zero: per-block check-off during the day is optional, and the absence of a row
in the log is a reading rather than a gap. One action converts presumption into record for a whole
day, any past day can be answered for at any later time, and correcting a past confirmation
re-derives everything projected from the log with no further call.

Import layout, so a reader knows where to look:

| Module | Holds |
|---|---|
| ``config.py`` | the two route prefixes, the lookback bound, and the wire bounds |
| ``days.py`` | how long a local day is, and which blocks belong to it |
| ``planned_days.py`` | a range of dates against the plans behind them, read once per week |
| ``ledger.py`` | the Today read model: the rows, the header figures, and what a settled day is |
| ``confirmations.py`` | which of a week's dates are settled, for the Week surface's own count |
| ``declarations.py`` | what a request asked to record |
| ``rules.py`` | the status each rejection carries |
| ``schemas.py`` | the wire shapes |
| ``service.py`` | authorization, the four acts, and the version bump |
| ``api.py`` | the four routes |
| ``injection.py`` | the one place its collaborators are composed, scoped to a tenant |
| ``wiring.py`` | the router the app factory asks for |

**The storage is not here.** ``block_outcomes`` is plan storage's table, and
:class:`syncr_api.plans.reality.BlockOutcomeRepository` is the one write path to it, for the same
reason the concession routes read plan storage's adjustment repository: the package that owns a
table owns the statements over it. What lives here is the reality-state half of the product,
answering for it over HTTP.

**The five states and what each attributes live in the domain.**
``syncr_domain.outcomes`` holds the vocabulary, the two required halves, and the attribution table
the probe's demand reads. Nothing in this package decides what a state means.

**The Today SCREEN is not here either.** This package ships the API and its read model; the screen
is ticket 45's.
"""
