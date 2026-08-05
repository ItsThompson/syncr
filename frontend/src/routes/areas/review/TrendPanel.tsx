/* Trend over time: stacked bars by week, in Area ink, hatched.
 *
 * NEVER A LINE CHART. The Area ramp is sealed to two chart carriers, a pie wedge fill and a stacked bar fill,
 * so a time series drawn as a line has no legal ink at all, and twelve cobalt lines separated only by dash
 * pattern is unreadable. The kit exports no line chart and its own test refuses one; this panel is the caller
 * that would have wanted one.
 *
 * EACH BAR IS NORMALISED TO ITS OWN TOTAL, so the reading is composition per week rather than volume per week.
 * A week that held less time still fills its bar and its label states which week it was.
 *
 * A QUARTER WITH NOTHING CONFIRMED DRAWS NO BARS. Every week would be one full vacancy bar, which reads as a
 * quarter in which the user did nothing rather than one nobody answered for. The api's own statement is
 * rendered instead. */

import { EmptyState, StackedBars } from "../../../ui/domain";
import { Panel } from "../../../ui/layout";
import { wedgesOf } from "../entries";
import { asWeekLabel } from "../figures";
import type { StackedBar } from "../../../ui/domain";
import type { Area } from "../../../api/hooks/useAreas";
import type { BudgetReview } from "../../../api/hooks/useBudgetReview";

export interface TrendPanelProps {
  readonly review: BudgetReview;
  readonly areas: readonly Area[];
}

export function TrendPanel({ review, areas }: TrendPanelProps) {
  /* An omitted field and a null one mean the same thing: the api has nothing to say about the quarter. */
  const nothingConfirmed = review.quarterDays.statement ?? null;
  const bars: readonly StackedBar[] = review.trend.map((week) => ({
    id: week.period,
    label: asWeekLabel(week.period),
    segments: wedgesOf(week.slices, areas),
  }));

  return (
    <Panel
      title="Trend over time"
      headerEnd={
        <span className="text-eyebrow">by week &middot; stacked, Area ink plus hatch</span>
      }
    >
      {nothingConfirmed === null ? (
        <StackedBars bars={bars} caption="Composition of discretionary time by week" />
      ) : (
        <EmptyState
          title="No week of the quarter has been answered for"
          detail={nothingConfirmed}
        />
      )}
    </Panel>
  );
}
