"""The words a raise uses: what to call a thing, and how to state a count of weeks.

Every raise in the weekly session names something and most of them count weeks, and each of those
two has exactly one statement here. That is the same discipline the pie review's ``statements``
module follows and it exists for the same reason: a figure or a label spelled twice is a figure or a
label two surfaces can render differently, and the whole justification for composing these sentences
server-side is that the words are the api's.

**A name comes from a BLOCK, because nothing else in this module's inputs holds one.** A conflict
row stores the binding it collided with, a pin row stores the same, and an outcome row stores the
same: none stores a title. The blocks of the weeks the session can see are the only place a name
exists without a second read, and :func:`block_titles` is that lookup.

**The fallback is ONE fallback.** A repeated collision's block and a promotion candidate's binding
both reach content the window cannot name, and both take :func:`a_kind`. Two spellings of one
absence on two surfaces of one payload is what this module exists to prevent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.identity import origin_of

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from uuid import UUID

    from syncr_domain.identity import BindingKind, BindingRef
    from syncr_domain.plan import Block
    from syncr_domain.weeks import IsoWeek

    # What `BindingRef.content_key` answers: the binding with its week-scoped occurrence dropped.
    type ContentKey = tuple[BindingKind, UUID, int | None]

# What `a_kind` takes `an` before. Written as the letters rather than as the one word that needs it
# today, so an eighth `Origin` member is spelled correctly by arriving rather than by being noticed.
VOWELS = "aeiou"


def block_titles(blocks: Iterable[Block]) -> Mapping[ContentKey, str]:
    """The title each content was last seen under, keyed so it can be found across weeks.

    A block's own title is the name the reader saw on the grid, and it is the only name a retained
    row can be given: a conflict stores the binding it collided with and nothing else, and an
    outcome stores the same. The key drops the occurrence, because an occurrence key is scoped to
    its own week and a name is not.

    ``blocks`` arrives OLDEST FIRST, so the most recent title wins a rename: what the reader last
    saw is what a raise should call it.
    """
    return {block.binding.content_key: block.title for block in blocks}


def content_key_text(binding: BindingRef) -> str:
    """A binding's content as one word, so a key names the thing rather than one week's occurrence.

    The occurrence key is what drops out, which is the reason both runs group on it: a chronic skip
    and a repeated collision are both about the content across weeks.
    """
    kind, entity_id, split_index = binding.content_key
    return f"{kind}:{entity_id}:{split_index}"


def a_kind(kind: BindingKind) -> str:
    """``a task``, ``an anchor``, ``a prep``: what to call content no block in the window names.

    A weaker label rather than a missing one, so an item the product decided to raise is still
    worth stating. It is the ONE fallback: a repeated collision's block and a promotion candidate's
    binding both take it, so two surfaces of one payload cannot spell the same absence two ways.

    **The word is ``Origin``'s, not ``BindingKind``'s, and the difference is the reader.**
    ``Origin`` is the vocabulary the grid and the ledger render, and it is where three of the seven
    kinds are spelled differently: an anchor's prep block is ``prep`` to a reader and
    ``anchor_prep`` on the wire. Reading the reader-facing enum rather than listing seven labels
    here is what keeps this total as well: a kind added to either enum arrives with its own word.

    The article is derived from the word for the same reason the word is not listed. ``an anchor``
    is the only vowel today, and a list would have had to be remembered when an eighth kind arrives.
    """
    word = origin_of(kind).value.replace("_", " ")
    article = "an" if word[:1] in VOWELS else "a"
    return f"{article} {word}"


def content_title(
    titles: Mapping[ContentKey, str], *, kind: BindingKind, entity_id: UUID
) -> str | None:
    """What the window called one content, whichever chunk of it a block named.

    The split index is dropped, which is what a caller holding no chunk needs: a repeated pin groups
    across chunks deliberately, so a candidate for a divided task carries the task and not the
    piece. A caller that HOLDS a whole content key looks it up directly instead, because a chunk's
    own title is the better answer when there is one.
    """
    for (block_kind, block_entity, _split), title in titles.items():
        if block_kind is kind and block_entity == entity_id:
            return title
    return None


def weeks_stated(count: int) -> str:
    """``6 weeks``, or ``1 week``. One rendering, so two kinds cannot spell one count two ways."""
    return f"{count} week{'' if count == 1 else 's'}"


def most_recently(weeks: Sequence[IsoWeek]) -> str:
    """Which week a pattern was last seen in, which tells a fresh raise from an expiring one.

    A run is bounded to the session's window, so a pattern that stopped a quarter ago falls out of
    the read entirely. What the window cannot say is WHERE inside itself a run sits: without this,
    a raise about three weeks that ended twelve weeks ago reads like one about last week. The data
    costs no read, because every run already carries every week it spans, oldest first.
    """
    return "" if not weeks else f" Most recently {weeks[-1]}."
