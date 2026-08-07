"""The plan horizon maintainer: the component that brings a week's plan into existence.

Every other trigger in the product is a MUTATION, and time passing is not a mutation, so this needed
a runner of its own. Without it nothing produces a plan for a week the user has not touched, and
three things break silently: the Week screen has nothing to render for a future week, the projector
runs out of revisions at the week boundary so the calendar goes blank, and the checkpoint's headline
capability has no producer.

| Module | Holds |
|---|---|
| ``config.py`` | the tick interval and the duty vocabulary the histogram is labeled by |
| ``weeks.py`` | the horizon span, the ISO weeks overlapping it, and the next local midnight |
| ``metrics.py`` | the horizon gauge, the tick histogram, and duty 2's direction counter |
| ``maintainer.py`` | duty 1: keep every horizon week supplied with a live plan |
| ``verdicts.py`` | duty 2: record the verdict transitions no mutation causes |
| ``runner.py`` | the worker duty: every fifteen minutes, and at each local midnight |

**The two duties run over one horizon.** The tick reads the clock once and each tenant's zone once,
duty 1 plans the weeks that hold no plan, and duty 2 probes the weeks that do. A second resolution
of the week list could answer differently across local midnight, so the list duty 1 resolved is what
duty 2 is handed.

Duty 2 is the only writer for a week that becomes infeasible because Monday's slack went unused. No
mutation causes that and no read may write, so without it the early-catch product metric's
denominator would lose its most ordinary case. The tick histogram carries a duty label because the
two costs are unrelated: duty 1 skips a planned week with one indexed read, and duty 2 assembles.
"""
