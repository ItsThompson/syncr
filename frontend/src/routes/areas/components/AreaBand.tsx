/* The screen's header band: the serif title, the counts, and the control that enters the review.
 *
 * THE TITLE IS SERIF AND IT IS THE PAGE'S. This is a destination, so it claims the type reserved for one; the
 * review's own header does not, because a mode is not a place.
 *
 * THE BAND RENDERS IN EVERY STATE, INCLUDING BEFORE THE READS ARRIVE. A screen's title is a fact about the
 * destination rather than about whether a response landed, and a reader who navigated here should be told where
 * they are while the figures are still coming. That is why the counts are optional rather than required: absent
 * is what "not yet known" looks like, and zero is a count that renders as one.
 *
 * ENTERING THE REVIEW IS A REAL LINK. `?mode=review` is a URL, so a link gives the reader middle-click,
 * cmd-click and the back button, and a button assigning a location would take all three away.
 *
 * THE PLATE IS IN THE BAND AND NOWHERE ELSE ON THIS SCREEN. Illustration belongs in headers, empty states and
 * dead space; a plate is never placed behind a chart, and the two panels below this band are charts. */

import { Link } from "react-router";

import { Plate } from "../../../ui/domain";
import { Button } from "../../../ui/primitives";
import { REVIEW_PATH } from "../mode";
import type { Area } from "../../../api/hooks/useAreas";
import type { BudgetReview } from "../../../api/hooks/useBudgetReview";

export interface AreaBandProps {
  /** Absent until the Area list arrives. An empty list is a reading and renders as one. */
  readonly areas?: readonly Area[] | undefined;
  readonly review?: BudgetReview | undefined;
}

function counts(areas: readonly Area[] | undefined): string {
  if (areas === undefined) return "reading your Areas";
  const floors = areas.filter((area) => area.floorHours !== null).length;
  return `${areas.length} ${areas.length === 1 ? "Area" : "Areas"} \u00b7 ${floors} ${
    floors === 1 ? "floor" : "floors"
  } declared`;
}

export function AreaBand({ areas, review }: AreaBandProps) {
  return (
    <section className="flex flex-wrap items-end gap-4 border-b border-rule-strong bg-paper-raised px-3.75 py-2.75">
      <div>
        <p className="text-eyebrow tracking-eyebrow uppercase text-text-muted">{counts(areas)}</p>
        <h1 className="font-serif text-title leading-tight text-ink-deep">Areas</h1>
      </div>
      <p className="text-eyebrow text-text-muted">
        Budgets are floors plus a proportional remainder, measured against discretionary time.
      </p>
      <div className="ml-auto flex items-center gap-3.25">
        <Plate name="armillary" fit="band" />
        <Button asChild rank="secondary">
          <Link to={REVIEW_PATH}>Run the pie review</Link>
        </Button>
      </div>
      {review === undefined ? null : (
        <p className="sr-only">{`${review.days.confirmed} of this week's days have been confirmed.`}</p>
      )}
    </section>
  );
}
