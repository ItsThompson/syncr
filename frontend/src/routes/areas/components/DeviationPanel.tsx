/* Actual against target: cobalt only, signed off a zero rule, and the days the figures rest on.
 *
 * NO AREA INK APPEARS IN THIS PANEL AT ALL, including the rows' label cells. `DeviationRow` carries no pigment
 * field, so nothing here could pass one; what this panel adds is that it draws no chip of its own either. A
 * chart row is a chart context end to end, and a chip beside a cobalt bar would imply the bar could have been
 * Area-coloured, which muddies the one rule the component exists to demonstrate. The Area's name identifies the
 * row, which is what a name is for.
 *
 * THE UNCONFIRMED DAY COUNT SITS BESIDE THE CAPTION, not inside a row. It is one statement about the period
 * rather than a fact about any Area: every row rests on the same days, so repeating it per row would repeat one
 * figure seven times. US-AREA-04 asks that the row state how many days were unconfirmed; the panel states it
 * once for every row it holds, which is the same claim without the repetition.
 *
 * OFF-PLAN DAYS ARE STATED SEPARATELY from unconfirmed ones, because a day the reader declared away is not a
 * day they failed to answer for. */

import { DeviationBar, EmptyState } from "../../../ui/domain";
import { Panel } from "../../../ui/layout";
import { deviationRowsOf } from "../entries";
import { asPoints } from "../figures";
import type { Area } from "../../../api/hooks/useAreas";
import type { BudgetReview } from "../../../api/hooks/useBudgetReview";

export interface DeviationPanelProps {
  readonly review: BudgetReview;
  readonly areas: readonly Area[];
}

/** One sentence naming the days the figures rest on, and the days nothing was owed for. */
function daysStatement(review: BudgetReview): string {
  const { confirmed, unconfirmed, offPlan } = review.days;
  const answered = `${confirmed} ${confirmed === 1 ? "day" : "days"} confirmed`;
  const outstanding = `${unconfirmed} unconfirmed`;
  const away = offPlan === 0 ? "" : `, ${offPlan} off-plan`;
  return `${answered}, ${outstanding}${away}. Only a confirmed day contributes to a figure here.`;
}

export function DeviationPanel({ review, areas }: DeviationPanelProps) {
  const rows = deviationRowsOf(review.categories, areas, review.discretionaryMinutes);

  return (
    <Panel
      title="Actual against target"
      headerEnd={
        <span className="text-eyebrow">this week &middot; percentage points off target</span>
      }
      footer={<span>{daysStatement(review)}</span>}
    >
      {rows.length === 0 ? (
        <EmptyState
          title="No Area has a target in this week"
          detail={
            review.statement ??
            "A target is a floor plus a share of the discretionary time the floors leave, so an Area " +
              "with neither declares no target and there is nothing to compare against."
          }
        />
      ) : (
        <DeviationBar
          rows={rows}
          caption="Actual against target per Area, in percentage points"
          format={asPoints}
        />
      )}
    </Panel>
  );
}
