/* `/areas`: wedges, floors, percentages, actual against target, and the pie review as a MODE.
 *
 * ONE READ FEEDS BOTH MODES. The review payload carries the named week's composition and deviation as well as
 * the quarter's trend and proposal, so the screen and the mode divide one denominator computed once. Two reads
 * would let the pie and the trend disagree about the same week.
 *
 * THE REVIEW IS A MODE, NOT A DESTINATION. `?mode=review` is a search parameter rather than component state, so
 * it survives a reload and can be linked; the mode header takes no serif title because a mode does not claim
 * the type reserved for a page.
 *
 * THE PERIOD IS THIS WEEK, DERIVED HERE. Which ISO week "now" falls in is a fact about the calendar, so it is
 * computed rather than read: there is no route that answers "which week is it", and asking the server would be
 * a read whose only output the client already has.
 *
 * THE BAND RENDERS BEFORE THE READS DO, and every state under it is static. A pending read says what it is
 * waiting for in words, a failure carries the api's own sentence and names which read it was, and a screen with
 * no Area points at the one act that fixes it. There is no spinner in the kit to paper over an ambiguous state,
 * which is why the hooks return a discriminated reading rather than independent booleans.
 *
 * WHICH PREFERENCE CELL IS OPEN IS THE ONLY STATE THIS SCREEN HOLDS. One at a time, held as the Area's id or
 * null rather than as a boolean per row, so two open editors are not representable. */

import { useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";

import { EmptyState, PendingState } from "../../ui/domain";
import { Button } from "../../ui/primitives";
import { SETUP_PATH } from "../../ui/domain/shell/navigation";
import { useAreaDeclaration, useAreas } from "../../api/hooks/useAreas";
import { useBudgetReview, useBudgetRevision } from "../../api/hooks/useBudgetReview";
import {
  useAreaPreferenceDeclaration,
  useAreaPreferenceRemoval,
  useAreaPreferences,
} from "../../api/hooks/usePreferences";
import { readingOf } from "../reading";
import { ReadFailure } from "../templates/components/ReadFailure";
import { AreaBand } from "./components/AreaBand";
import { AreaScreen } from "./components/AreaScreen";
import { isReviewMode } from "./mode";
import { ReviewMode } from "./review/ReviewMode";
import { thisIsoWeek } from "./week";

export function AreasRoute() {
  const [search] = useSearchParams();
  const [editingAreaId, setEditingAreaId] = useState<string | null>(null);
  const period = thisIsoWeek(new Date());
  const isReview = isReviewMode(search);

  const areas = useAreas();
  const review = useBudgetReview(period);
  const areaIds = areas.status === "ready" ? areas.data.areas.map((area) => area.id) : null;
  const preferences = useAreaPreferences(areaIds);

  const declareArea = useAreaDeclaration(period);
  const declarePreference = useAreaPreferenceDeclaration(areaIds ?? [], period);
  const removePreference = useAreaPreferenceRemoval(areaIds ?? [], period);
  const applyRevision = useBudgetRevision(period);

  const reading = readingOf({ Areas: areas, review, preferences });

  /* The band is drawn above whatever the state is, so the destination names itself while the figures are still
   * coming. The mode gets none of it: its own header is what a mode has instead. */
  const under = (surface: ReactElement) =>
    isReview ? (
      surface
    ) : (
      <>
        <AreaBand />
        <div className="px-3.75 py-3.25">{surface}</div>
      </>
    );

  if (reading.status === "loading") {
    return under(
      <PendingState
        title="Reading your Areas and this week's budget"
        detail="The Areas you have declared, what each held, and when each one's work should happen."
      />,
    );
  }
  if (reading.status === "error") {
    return under(
      <ReadFailure title={`The ${reading.name} could not be read`} problem={reading.problem} />,
    );
  }

  const { Areas: declared, review: reviewed, preferences: declaredPreferences } = reading.data;

  if (declared.areas.length === 0) {
    return under(
      <EmptyState
        title="No Area is declared"
        detail={
          "An Area is a category of your time, and a budget is floors plus a share of what remains. " +
          "Setup declares the first ones, which is one of the two things syncr needs before it can solve."
        }
        action={
          <Button asChild rank="secondary">
            <Link to={SETUP_PATH}>Go to setup</Link>
          </Button>
        }
      />,
    );
  }

  if (isReview) {
    return <ReviewMode review={reviewed} areas={declared.areas} write={applyRevision} />;
  }

  return (
    <AreaScreen
      declared={declared}
      review={reviewed}
      preferences={declaredPreferences}
      editingAreaId={editingAreaId}
      onEdit={setEditingAreaId}
      declarePreference={declarePreference}
      removePreference={removePreference}
      declareArea={declareArea}
    />
  );
}
