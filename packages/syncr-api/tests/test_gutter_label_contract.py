"""The gutter's wordings have one home, and this is the crossing that keeps the client out of it.

Each empty-slot reason renders exactly one wording, defined in :mod:`syncr_domain.gaps`, and the
week payload now carries the rendered string. So the grid reads it. A second copy of any wording in
the client is the thing that rule exists to forbid: it would go stale silently, because a wording it
disagreed with would still draw.

**The wordings are read from the vocabulary rather than listed here.** A member added to the enum is
covered by this reading on the commit that adds it, with no list to remember.

**What is scanned, and what is not.** The trees the week's gutter is drawn from, source only. Two
exclusions, both deliberate rather than convenient:

- **Test modules.** A case asserting the words it fed a stub is not a second statement of the rule,
  and one of them legitimately asserts a refusal sentence the api sends that shares two words with a
  wording here.
- **The rest of the client.** The wordings are made of ordinary words, and other screens use some of
  them for their own subjects: the off-plan feature's own copy names it in prose. A reading over the
  whole tree would need a hand-written exemption per wording, and an exemption list is defeated by
  whoever adds the next one.

So this reading is narrow on purpose: it covers the files where a gutter wording could actually be
composed, and it says so rather than implying it covers the client.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from syncr_domain.gaps import EmptySlotReason, SlotContext, gutter_label
from tests.test_alert_rules import repo_root

if TYPE_CHECKING:
    from pathlib import Path

# The trees the week's gutter is drawn from: the screen that maps a gap onto a band, and the kit
# that draws one.
GUTTER_TREES = ("frontend/src/routes/week", "frontend/src/ui/domain")

# A name no Area could be called, so a wording that substitutes one splits at a character no source
# contains and the literals it is made of come back separately.
SENTINEL = "\x00"


def gutter_sources() -> tuple[Path, ...]:
    """Every client source the gutter is drawn from, as the index holds them, tests excluded.

    Git answers what the files are rather than a walk: a file added to either tree is covered
    without anyone remembering to add it, and a generated or ignored file cannot creep in.
    """
    listed = subprocess.run(  # noqa: S603 - the arguments are this module's own constants
        ["git", "ls-files", "--cached", "-z", *GUTTER_TREES],  # noqa: S607
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=True,
    )
    found = tuple(
        repo_root() / name
        for name in listed.stdout.split("\0")
        if name and "__tests__" not in name and ".test." not in name
    )
    assert found, f"git listed no source under {GUTTER_TREES}, so this reading covers nothing"
    return found


def longest_literal(reason: EmptySlotReason) -> str:
    """The longest run of fixed text this reason's wording is made of.

    A wording that names the Area is part fixed text and part substitution, so the fixed halves are
    what a copy of it would have to contain. The longest of them is the one distinctive enough to
    search for: the shorter halves are single ordinary words.
    """
    rendered = gutter_label(reason, SlotContext(area_name=SENTINEL))
    return max(rendered.split(SENTINEL), key=len).strip()


@pytest.mark.parametrize(
    "reason", list(EmptySlotReason), ids=[reason.value for reason in EmptySlotReason]
)
def test_no_gutter_source_restates_a_wording_the_domain_defines(reason: EmptySlotReason) -> None:
    """Driven over whatever members the vocabulary holds, so a member added is covered at once."""
    literal = longest_literal(reason)
    restating = [
        source.relative_to(repo_root())
        for source in gutter_sources()
        if literal in source.read_text(encoding="utf-8")
    ]

    assert not restating, (
        f"{reason.value}'s wording is stated in syncr_domain.gaps and reaches the client on the "
        f"wire, so {literal!r} in {[str(path) for path in restating]} is a second statement of it"
    )


def test_every_reason_yields_a_literal_long_enough_to_be_worth_searching_for() -> None:
    """The positive control: a wording reduced to a word or two would make the reading above pass
    over anything.

    It is the substituting wordings this can go wrong for, because their fixed halves are shorter
    than the whole. One added as a bare substitution would leave nothing distinctive to search for.
    """
    shortest = min(longest_literal(reason) for reason in EmptySlotReason)

    assert len(shortest.split()) > 1, (
        f"{shortest!r} is the most distinctive text one wording holds, and a single word is not "
        "distinctive enough to tell a copy of a wording from ordinary prose"
    )
