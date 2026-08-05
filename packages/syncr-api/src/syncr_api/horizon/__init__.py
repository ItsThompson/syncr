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
| ``metrics.py`` | the horizon gauge and the tick histogram |
| ``maintainer.py`` | duty 1: keep every horizon week supplied with a live plan |
| ``runner.py`` | the worker duty: every fifteen minutes, and at each local midnight |

**Duty 2 is not here.** Recording time-driven verdict transitions needs the feasibility probe and
``VerdictEvent``, and it is the only writer for a week that becomes infeasible because Monday's
slack
went unused. It joins :mod:`syncr_api.horizon.maintainer` as a second duty, which is why the tick
histogram carries a duty label from the start: the two costs have to be separable, and a label added
later would leave the first duty's history unlabeled.
"""
