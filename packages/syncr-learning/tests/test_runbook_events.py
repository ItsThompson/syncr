"""The log events the operator's runbook tells them to look for, against what this package emits.

A runbook is read once, under pressure, by someone deciding whether to intervene. One that names an
event nothing emits sends them looking for evidence that does not exist, and a `grep` that returns
nothing reads as "the run never got there" rather than as "the runbook is wrong".

The event names are READ OUT of the runbook rather than restated here, so a name added to it is
covered without this module changing. The scan is held to answering "no" as well as "yes", because a
scan that reported every name as emitted would pass this file forever.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

_ROOT: Final = Path(__file__).resolve().parents[3]

RUNBOOK: Final = _ROOT / "docs" / "runbooks" / "learning-job-failed.md"
SOURCE: Final = Path(__file__).resolve().parents[1] / "src" / "syncr_learning"

# A whole backticked token, so `syncr_learning.prom` is a filename rather than a truncated event.
_NAMED_EVENT = re.compile(r"`(learning\.[a-z_.]+)`")


def named_events() -> set[str]:
    return set(_NAMED_EVENT.findall(RUNBOOK.read_text(encoding="utf-8")))


def is_emitted(event: str) -> bool:
    """Whether any module of this package logs ``event`` as a literal."""
    return any(f'"{event}"' in path.read_text(encoding="utf-8") for path in SOURCE.rglob("*.py"))


def test_the_runbook_names_at_least_one_event_to_look_for() -> None:
    # The inventory below is only meaningful while the runbook still names events. Without this, a
    # rewrite that dropped them all would leave the crossing asserting nothing.
    assert named_events()


def test_every_event_the_runbook_names_is_one_this_package_emits() -> None:
    assert {event for event in named_events() if not is_emitted(event)} == set()


def test_the_scan_can_answer_no() -> None:
    # The control. Without it, an `is_emitted` that always answered yes would pass the crossing
    # above over any runbook at all.
    assert not is_emitted("learning.nothing.emits_this")
