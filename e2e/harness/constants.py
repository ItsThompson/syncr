#!/usr/bin/env python3
"""Print the domain fixtures' own numbers, so the stack-level seeds do not restate them.

Five of the fixtures section 20's table names already exist in the source tree, as frozen values the
domain and api suites assert against: ``syncr_domain.fixtures``. They cannot be loaded into a
running stack, because every instant in them is a literal in February or October 2026 and every
identifier is a synthetic UUID. What CAN be shared is the arithmetic each one is about -- how much
give a sleep routine has, how long a recovery window is, what a partially progressed task's estimate
is -- and that is what this prints.

Run as a one-shot in the api image::

    docker compose -f docker-compose.yml -f e2e/docker-compose.e2e.yml \\
      run --rm --no-deps worker python /harness/constants.py

WHY THIS EXISTS RATHER THAN A NUMBER IN THE SEED. A seed holding ``460`` would be a second copy of a
fact, and the day the domain fixture's minimum moved, the stack fixture would keep straddling
nothing while still being named ``elastic_sleep``. The fixture's own docstring makes the same
argument about why its sizes are computed from the thresholds rather than written down.
"""

from __future__ import annotations

import json
import sys

from syncr_domain.fixtures import dst_weeks, elastic_sleep, partial_progress, recovery_scopes


def constants() -> dict[str, dict[str, object]]:
    """The numbers a stack-level seed needs, per fixture, named as the fixture names them."""
    return {
        "elastic_sleep": {
            "title": elastic_sleep.TITLE,
            "targetTime": elastic_sleep.TARGET_TIME.isoformat(),
            "durationMinutes": elastic_sleep.DURATION_MINUTES,
            "minDurationMinutes": elastic_sleep.MIN_DURATION_MINUTES,
            "giveMinutes": elastic_sleep.GIVE_MINUTES,
            "gapMinutes": elastic_sleep.GAP_MINUTES,
            "reductionEach": elastic_sleep.REDUCTION_EACH,
        },
        "partial_progress": {
            "title": partial_progress.TITLE,
            "estimateMinutes": partial_progress.ESTIMATE_MINUTES,
            "remainingMinutes": partial_progress.REMAINING_MINUTES,
            "careerFloorMinutes": partial_progress.CAREER_FLOOR_MINUTES,
            "fitnessFloorMinutes": partial_progress.FITNESS_FLOOR_MINUTES,
        },
        "recovery_scopes": {
            "label": recovery_scopes.LABEL,
            "recoveryMinutes": recovery_scopes.RECOVERY_MINUTES,
        },
        "dst_weeks": {
            "zone": dst_weeks.LONDON,
            "sleepTargetTime": dst_weeks.SLEEP_TARGET_TIME.isoformat(),
            "sleepDurationMinutes": dst_weeks.SLEEP_DURATION_MINUTES,
        },
    }


if __name__ == "__main__":
    json.dump(constants(), sys.stdout)
    sys.stdout.write("\n")
