/* The pie review, as a MODE of the Areas screen.
 *
 * NO SERIF TITLE. A page title is serif and a mode header is not, because a mode is not a destination and so
 * does not claim the type reserved for one. The header is a band with the mode's name in the label face, the
 * eyebrow that says when a review runs, and a link back to the screen.
 *
 * THE MODE IS REACHABLE BY URL, so it survives a reload and can be linked. Leaving it is a real link rather
 * than a click handler that assigns a location, which is what keeps middle-click and cmd-click working.
 *
 * WHAT THE MODE ADDS is the trend and the proposal. The composition and the deviation are the screen's own and
 * are rendered by the screen either way: a mode is a way of using a screen, not a second screen. */

import { Link } from "react-router";

import { CompositionPanel } from "../components/CompositionPanel";
import { ProposalPanel } from "./ProposalPanel";
import { TrendPanel } from "./TrendPanel";
import { AREAS_PATH } from "../mode";
import type { Area } from "../../../api/hooks/useAreas";
import type { BudgetReview, BudgetRevisionBody } from "../../../api/hooks/useBudgetReview";
import type { Write } from "../../../api/hooks/useWrite";

export interface ReviewModeProps {
  readonly review: BudgetReview;
  readonly areas: readonly Area[];
  readonly write: Write<BudgetRevisionBody>;
}

export function ReviewMode({ review, areas, write }: ReviewModeProps) {
  const confirmed = review.proposal.confirmedWeeks;

  return (
    <section aria-label="Pie review">
      {/* The mode header. Deliberately not an h1 and deliberately not serif: see the module note. */}
      <div className="flex flex-wrap items-center gap-3.25 border-b border-rule-strong bg-paper-raised px-3.75 py-2">
        <b className="text-label tracking-label uppercase text-ink-deep">Pie review</b>
        <span className="text-eyebrow text-text-muted">
          Quarterly, or whenever you ask &middot; syncr proposes, you decide
        </span>
        <Link className="ml-auto text-sm underline" to={AREAS_PATH}>
          Leave the review
        </Link>
      </div>
      <div className="flex flex-col gap-3.25 px-3.75 py-3.25">
        <div className="flex flex-wrap items-start gap-3.25">
          <CompositionPanel
            review={review}
            areas={areas}
            note={`${confirmed} confirmed ${confirmed === 1 ? "week" : "weeks"}`}
          />
          <TrendPanel review={review} areas={areas} />
        </div>
        <ProposalPanel proposal={review.proposal} areas={areas} write={write} />
      </div>
    </section>
  );
}
