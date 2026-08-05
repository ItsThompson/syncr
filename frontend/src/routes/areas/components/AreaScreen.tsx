/* The Areas screen once its reads have arrived: the band, the two residual notices, the two charts, the budget
 * sheet, and the panel that declares an Area.
 *
 * SEPARATE FROM THE ROUTE because the route is the gate and this is the composition. The route owns the reads,
 * the mode and the one piece of state this screen has; everything here takes data as props, so each part is
 * testable without a network fixture.
 *
 * THE DEVIATION PANEL COMES FIRST, as the rendered sheet draws it: the question a reader opens this screen with
 * is "which Area is starving", and the composition answers a different one beside it. */

import { AreaBand } from "./AreaBand";
import { AreaCreator } from "./AreaCreator";
import { AreaTable } from "./AreaTable";
import { CompositionPanel } from "./CompositionPanel";
import { DeviationPanel } from "./DeviationPanel";
import { ResidualNotices } from "./ResidualNotices";
import type { Area, AreaDeclarationBody, Areas } from "../../../api/hooks/useAreas";
import type { BudgetReview } from "../../../api/hooks/useBudgetReview";
import type {
  AreaPreferenceEdit,
  AreaPreferenceRemoval,
  PreferenceSet,
} from "../../../api/hooks/usePreferences";
import type { Write } from "../../../api/hooks/useWrite";

export interface AreaScreenProps {
  readonly declared: Areas;
  readonly review: BudgetReview;
  readonly preferences: PreferenceSet;
  /** Which row's Preference cell is open, or null. One at a time, by construction. */
  readonly editingAreaId: string | null;
  readonly onEdit: (areaId: string | null) => void;
  readonly declarePreference: Write<AreaPreferenceEdit>;
  readonly removePreference: Write<AreaPreferenceRemoval>;
  readonly declareArea: Write<AreaDeclarationBody>;
}

export function AreaScreen({
  declared,
  review,
  preferences,
  editingAreaId,
  onEdit,
  declarePreference,
  removePreference,
  declareArea,
}: AreaScreenProps) {
  const areas: readonly Area[] = declared.areas;

  return (
    <>
      <AreaBand areas={areas} review={review} />
      <div className="flex flex-col gap-3.25 px-3.75 py-3.25">
        <ResidualNotices review={review} />
        <div className="flex flex-wrap items-start gap-3.25">
          <DeviationPanel review={review} areas={areas} />
          <CompositionPanel review={review} areas={areas} note="this week" />
        </div>
        <AreaTable
          areas={areas}
          review={review}
          preferences={preferences}
          editingAreaId={editingAreaId}
          onEdit={onEdit}
          declare={declarePreference}
          remove={removePreference}
        />
        <AreaCreator ramp={declared.ramp} write={declareArea} />
      </div>
    </>
  );
}
