"""The two statements the Learned screen makes in prose, beside the figures they qualify.

Served by the api rather than left in the client's own copy, because each is a claim about how this
system works and a claim a client can render without is one it will eventually render wrongly.

They are duplicated from ``syncr_learning.gates``, which cannot be imported here: that package pulls
scipy and the api image must not carry it. The learning suite's agreement test crosses the first of
the two against this constant, so the two copies cannot drift.
"""

from __future__ import annotations

from typing import Final

THRESHOLDS_ARE_ESTIMATES: Final = (
    "These thresholds are estimates rather than measurements. Revising one can move a gate in "
    "either direction without losing any confirmation you have recorded."
)
"""Because they are guesses, and asserting a guess as a measurement would break the product's own
standard."""

UNLOCKS_COUNT_CONFIRMED_VOLUME: Final = (
    "Progress counts days you have confirmed, not days that went to plan. A day where you skipped "
    "everything and said so counts exactly as much as a perfect one, and confirming a past day "
    "later counts the same as confirming it that evening."
)
"""So the user understands that honesty is not penalised.

The integrity of the whole dataset rests on honest confirmation: an unlock tied to adherence would
reward marking things done, and every parameter fitted afterwards would be fitted to a fiction.
"""

COLLECTING_IS_NORMAL: Final = (
    "A parameter still collecting is normal. Nothing is broken while syncr gathers enough of your "
    "own history to say something about it."
)
"""Rendered at informational volume, never as a warning.

Marking a collecting parameter as a fault would teach the user to distrust a system that is working.
"""
