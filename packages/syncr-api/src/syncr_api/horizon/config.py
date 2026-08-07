"""The maintainer's cadence, and the duty vocabulary its histogram is labeled by.

**Every fifteen minutes and at each local midnight**, and the second is not implied by the first.
The horizon is ``[today_local, today_local + horizon_days)``, so it advances AT local midnight; a
pure fifteen-minute cadence would advance it up to fifteen minutes late, and the phase of that cycle
is whatever a restart happened to leave. The runner therefore takes the earlier of its next interval
and the next local midnight, which it can compute for free because a pass has already read every
tenant's zone.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Final


class MaintainerDuty(StrEnum):
    """Which duty a tick spent its time on. The one label on the tick histogram.

    Two duties with unrelated costs, which is why the label exists rather than one histogram over
    both: duty 1 plans the weeks WITHOUT a plan, and a tick on which every week already has one
    costs one indexed read per week; duty 2 assembles and probes every week WITH one, which is
    roughly 288 assemblies a day. A histogram that mixed them could not be read, and the label was
    added before the second duty existed so the first duty's whole history is comparable across the
    change.
    """

    HORIZON = "horizon"
    VERDICTS = "verdicts"


# How often the maintainer plans. Fifteen minutes bounds the lag between a week entering the horizon
# and its plan existing, on a horizon measured in days, so the interval buys promptness on a change
# to `horizon_days` rather than on the passage of time.
MAINTAINER_INTERVAL: Final = timedelta(minutes=15)
