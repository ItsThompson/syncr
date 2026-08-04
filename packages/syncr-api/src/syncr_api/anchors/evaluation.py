"""Re-evaluating the rules against the anchors a tenant already holds.

Reordering rules re-evaluates existing anchors, and so does every other edit to the rule set: a
created type may match commitments that arrived last week, an edited match rule changes which
ones it claims, and a removed type leaves its anchors for whichever rule matches next. All four
are the same pass, so there is one implementation of it rather than one per route.

**An overridden anchor is never re-evaluated.** The repository's read excludes it, so the
exclusion is one predicate in one statement rather than a condition each caller remembers. That
is what "an override survives rule changes" means concretely.

Only a changed assignment is written. A tenant with two hundred anchors and one reordered rule
that changes nothing issues no writes at all, which matters because every one of these passes
runs inside the request that caused it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.anchors.matching import first_match
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from syncr_api.anchors.repository import AnchorRepository
    from syncr_api.anchors.type_repository import AnchorTypeRepository

_log = get_logger("syncr.anchors")


class RuleEvaluator:
    """Applies one tenant's match rules to the anchors whose type a rule may still decide."""

    def __init__(self, anchors: AnchorRepository, types: AnchorTypeRepository) -> None:
        self._anchors = anchors
        self._types = types

    @measured("anchors")
    async def re_evaluate(self) -> int:
        """Re-match every non-overridden anchor, and report how many changed type.

        The rules are read once and the anchors once, so the pass costs two reads plus one write
        per anchor whose answer actually moved.
        """
        types = await self._types.list_all()
        retyped = 0
        for anchor in await self._anchors.list_matchable():
            matched = first_match(types, title=anchor.title, source_id=anchor.source_id)
            if matched == anchor.anchor_type_id:
                continue
            await self._anchors.set_matched_type(anchor.id, anchor_type_id=matched)
            retyped += 1
        if retyped:
            _log.info("anchors.rules.re_evaluated", anchors_retyped=retyped, rule_count=len(types))
        return retyped
