/* THE WEEK SCREEN'S BAND: the counts, the zoom reading, `Re-solve` and `Approve`.
 *
 * `Re-solve` DISPATCHES IMMEDIATELY, bypassing the debounce, and it is available whether or not a solve is already
 * pending: a reader who wants the plan now should never have to wait out a window they cannot see. The staleness rules
 * are the same as for any other trigger, so a solve already running is superseded by this one rather than blocked.
 *
 * `Approve` IS NEVER DISABLED BY AN INFEASIBILITY. syncr informs; it does not govern. The one thing that disables it is
 * having nothing to approve, which is a fact about the pending slot rather than a judgement about the week.
 *
 * THE PLAN CURRENCY IS NOT STATED HERE. It rides in the summary strip's `SCHEDULED` sub-line, BECAUSE it qualifies the
 * block count, and a band that repeated the word would be the second surface the rule exists to prevent. The count
 * here is the same figure the strip's cell reads, which is why the two cannot disagree about it. */

import { KeyHint } from "../../../ui/domain";
import { Button } from "../../../ui/primitives";

export interface WeekActionsProps {
  readonly blockCount: number;
  readonly visibleHours: number;
  readonly hasProposal: boolean;
  readonly onResolveNow: () => void;
  readonly onApprove: () => void;
}

export function WeekActions({
  blockCount,
  visibleHours,
  hasProposal,
  onResolveNow,
  onApprove,
}: WeekActionsProps) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <p className="text-eyebrow text-text-muted">
        {blockCount} blocks · {visibleHours}h visible <KeyHint keys="z" />
      </p>
      <Button onClick={onResolveNow} rank="secondary" size="sm">
        Re-solve
      </Button>
      <Button isDisabled={!hasProposal} onClick={onApprove} rank="primary" size="sm">
        Approve <KeyHint keys="Shift+A" />
      </Button>
    </div>
  );
}
