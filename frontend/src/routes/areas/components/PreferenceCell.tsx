/* One Area's Preference cell: what is in effect, where it came from, and the control that edits it.
 *
 * EDITABLE IN PLACE. The cell is a button that becomes the editor in the same cell, so authoring a placement
 * window never leaves the table the Area's other properties live in. That is the reason the column is here
 * rather than on a settings screen: a preference belongs to an Area, and this is where an Area's properties
 * already are.
 *
 * THE CELL STATES WHERE THE PREFERENCE CAME FROM, which is the api's own sentence rather than this screen's
 * paraphrase of it. `effective.statement` says `Set on this area: ...` or `Inherited from its Area: ...`, and
 * an Area's own preference is always the former; the inherited wording exists for a habit or a task, which
 * this table does not draw. Rendering the api's sentence rather than deriving one is what keeps the two from
 * disagreeing when the resolution chain changes.
 *
 * NOTHING HERE SPINS AND THERE IS NO SUBMITTING STATE. A refusal replaces the last one and a success clears
 * it, which is the whole of what a write reports. */

import { Button } from "../../../ui/primitives";
import { PreferenceEditor } from "./PreferenceEditor";
import { preferenceCellText } from "../preference";
import type {
  AreaPreferenceEdit,
  AreaPreferenceRemoval,
  Preference,
} from "../../../api/hooks/usePreferences";
import type { Write } from "../../../api/hooks/useWrite";

export interface PreferenceCellProps {
  readonly areaId: string;
  readonly areaName: string;
  readonly preference: Preference | undefined;
  /** True while this row's cell is the one being edited. One editor at a time, by construction. */
  readonly isEditing: boolean;
  readonly onEdit: (areaId: string | null) => void;
  readonly declare: Write<AreaPreferenceEdit>;
  readonly remove: Write<AreaPreferenceRemoval>;
}

export function PreferenceCell({
  areaId,
  areaName,
  preference,
  isEditing,
  onEdit,
  declare,
  remove,
}: PreferenceCellProps) {
  if (isEditing) {
    return (
      <PreferenceEditor
        areaId={areaId}
        areaName={areaName}
        preference={preference}
        onClose={() => onEdit(null)}
        declare={declare}
        remove={remove}
      />
    );
  }

  return (
    <span className="flex flex-col items-start gap-1">
      <Button rank="tertiary" onClick={() => onEdit(areaId)}>
        {preferenceCellText(preference?.effective)}
      </Button>
      {preference?.effective === null || preference?.effective === undefined ? null : (
        <span className="text-eyebrow text-text-muted">{preference.effective.statement}</span>
      )}
    </span>
  );
}
