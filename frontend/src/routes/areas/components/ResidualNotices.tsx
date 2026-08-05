/* The two residuals, each as its own named quantity and never as the other.
 *
 * `Unallocated` IS DISCRETIONARY TIME IN NO BLOCK AT ALL. Its being the largest wedge is the point of the
 * screen rather than a defect, which is why this reads at amber panel volume: it needs attention and nothing
 * is broken. The figure is coverage, not a residual against the Area targets, so setting the shares to sum to
 * exactly 100 does not make it zero.
 *
 * OVERSUBSCRIPTION IS THE OTHER QUANTITY, reported separately and in its own notice. It is how far the Area
 * targets exceed discretionary time, and it is never rendered as a negative `Unallocated`: a budget that does
 * not fit is accepted and reported, never refused, and a negative vacancy is not a wedge.
 *
 * BOTH NOTICES ARE STATIC AND NEITHER SPINS, because nothing in this product does. */

import { NoticePanel } from "../../../ui/domain";
import { asHours, asPercent, shareOf } from "../figures";
import type { Notice } from "../../../ui/domain";
import type { BudgetReview } from "../../../api/hooks/useBudgetReview";

export interface ResidualNoticesProps {
  readonly review: BudgetReview;
}

/** What the vacancy is called in the notice's own title. */
const VACANCY_TITLE = "Unallocated is discretionary time no block covers";

function vacancyNotice(minutes: number, discretionary: number): Notice {
  const share = shareOf(minutes, discretionary);
  return {
    id: "areas.unallocated",
    volume: "panel",
    pigment: "amber",
    title: `${VACANCY_TITLE}, and that is the point`,
    detail:
      `${asHours(minutes)} of ${asHours(discretionary)} discretionary hours, ${asPercent(share)}, ` +
      "sit in no block at all. Shares are measured against discretionary time rather than against " +
      "scheduled time, and the residual is shown rather than hidden: measuring against scheduled " +
      "time would inflate every Area's share by excluding exactly the hours nobody planned, and the " +
      "report would read as healthy while the gap grew.",
    unavailable: [],
    stillWorks: [
      "Every Area's target and actual are unaffected",
      "Declaring a share for the gap is one edit in the table below",
    ],
    since: null,
    action: null,
    scope: { screen: "areas" },
  };
}

function oversubscriptionNotice(minutes: number, discretionary: number): Notice {
  return {
    id: "areas.oversubscription",
    volume: "panel",
    pigment: "amber",
    title: "The Area targets ask for more time than the week holds",
    detail:
      `The targets exceed discretionary time by ${asHours(minutes)}, against ${asHours(discretionary)} ` +
      "available. This is oversubscription and it is its own quantity: shares summing past 100 are a " +
      "legitimate declaration, so they are accepted and reported rather than refused, and the " +
      "unallocated figure stays whatever no block covered rather than going negative.",
    unavailable: [],
    stillWorks: [
      "The week still solves, and the solver honours every floor first",
      "Unallocated still reports what no block covered",
    ],
    since: null,
    action: null,
    scope: { screen: "areas" },
  };
}

export function ResidualNotices({ review }: ResidualNoticesProps) {
  const discretionary = review.discretionaryMinutes;
  if (discretionary === null || discretionary === 0) return null;

  const vacancy = review.unallocatedMinutes;
  const excess = review.oversubscriptionMinutes;

  return (
    <>
      {vacancy === null || vacancy === 0 ? null : (
        <NoticePanel notice={vacancyNotice(vacancy, discretionary)} />
      )}
      {excess === null || excess === 0 ? null : (
        <NoticePanel notice={oversubscriptionNotice(excess, discretionary)} />
      )}
    </>
  );
}
