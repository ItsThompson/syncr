/* Composition now: the pie, its legend, and the denominator every share is measured against.
 *
 * THE HEADER STATES THE DISCRETIONARY FIGURE, which is US-AREA-01's own criterion: percentages mean nothing
 * without the quantity they divide, and a reader who cannot see it cannot tell 30% from three hours.
 *
 * A PERIOD WITH NO CONFIRMED DAY DRAWS NO PIE. Every Area would read as zero and the vacancy as the whole
 * week, which is a chart that says the user did nothing rather than one that says nobody answered for the
 * week. The api's own statement is rendered instead, which is what US-REV-04 asks for.
 *
 * NO PLATE GOES BEHIND A CHART. The header band above carries the illustration; this panel gets none. */

import { AreaLegend, EmptyState, PieChart } from "../../../ui/domain";
import { Panel } from "../../../ui/layout";
import { legendOf, wedgesOf } from "../entries";
import { asHours } from "../figures";
import type { Area } from "../../../api/hooks/useAreas";
import type { BudgetReview } from "../../../api/hooks/useBudgetReview";

export interface CompositionPanelProps {
  readonly review: BudgetReview;
  readonly areas: readonly Area[];
  /** `Composition now` on the screen, and the confirmed-week count in the review. */
  readonly note: string;
}

export function CompositionPanel({ review, areas, note }: CompositionPanelProps) {
  /* An omitted field and a null one mean the same thing here: the api has nothing to say about this
   * period, so the charts are what the panel draws. Read once so the check and the render agree. */
  const nothingConfirmed = review.days.statement ?? null;
  const denominator =
    review.discretionaryMinutes === null
      ? "no discretionary time yet"
      : `of ${asHours(review.discretionaryMinutes)} discretionary`;

  return (
    <Panel
      title="Composition now"
      headerEnd={<span className="text-eyebrow">{`${note} \u00b7 ${denominator}`}</span>}
    >
      {nothingConfirmed === null ? (
        <>
          <PieChart
            slices={wedgesOf(review.categories, areas)}
            caption="Composition of discretionary time by Area"
          />
          <AreaLegend
            entries={legendOf(review.categories, areas, review.discretionaryMinutes)}
            label="Each category and its share of discretionary time"
          />
        </>
      ) : (
        <EmptyState title="Nothing has been answered for yet" detail={nothingConfirmed} />
      )}
    </Panel>
  );
}
