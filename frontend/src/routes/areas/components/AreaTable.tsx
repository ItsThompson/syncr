/* The budget sheet: the rendered screen's columns, in its order, plus the Preference column this spec adds.
 *
 * THE ORDER IS `screens.html`'s: Area, Parent, Floor per week, Share of remainder, This week, Deviation, and
 * then Preference. `Pigment` is deliberately absent: a step of the ramp appears in the setup wizard's
 * assignment table, where it is being ASSIGNED, and here the chip carries it. Reading a value the user cannot
 * choose would be a column of noise.
 *
 * THE CHIP IS HERE AND NOT IN THE DEVIATION CHART, and the difference is the whole carrier rule. A table row is
 * a ledger row, where a chip beside the name is the sanctioned Area carrier; a chart row is a chart context end
 * to end, where cobalt encodes magnitude and Area ink would be a second channel for one reading.
 *
 * THE DEVIATION CELL IS A SIGNED FIGURE, NEVER A HUE. `+` or U+2212, with the same ink either way: being five
 * hours under on Research is neither a status nor a severity, and a signal pigment is sealed to those.
 *
 * EVERY CHIP'S INK BELONGS TO ONE AREA. The deal skips the steps already held, a declaration past twelve is
 * refused, and a re-pick onto a step another Area holds is refused too, so two rows in this table never show
 * one ink for two Areas. The name beside the chip stays required, because ink is never the whole of what
 * identifies an Area, which is why `AreaChip` requires one. */

import { AreaChip, MINUS_SIGN, Table, areaPigment, type TableColumn } from "../../../ui/domain";
import { PreferenceCell } from "./PreferenceCell";
import { hoursOf } from "../entries";
import { asFloor, asPoints, asWholePercent, shareOf } from "../figures";
import type { Area } from "../../../api/hooks/useAreas";
import type { BudgetReview, ReviewCategory } from "../../../api/hooks/useBudgetReview";
import type {
  AreaPreferenceEdit,
  AreaPreferenceRemoval,
  PreferenceSet,
} from "../../../api/hooks/usePreferences";
import type { Write } from "../../../api/hooks/useWrite";

/** U+2014, which is the width of the column's own dash rather than a hyphen standing in for one. */
const NOTHING = "\u2014";

/* THE AREA COLUMN ABSORBS THE SURPLUS. Every other column holds a figure, a parent's name or one control, and
 * each takes the width that clears its own widest ordinary content; what is left is the Area's, so a long Area
 * name spends its own row's height rather than reshaping the figures a reader compares down their columns. The
 * lengths clear their headers on one line, which keeps the header row at the pitch the adopting tables share. */
const PARENT_W = "96px";
const FLOOR_W = "56px";
const SHARE_W = "88px";
const THIS_WEEK_W = "64px";
const DEVIATION_W = "72px";
const PREFERENCE_W = "240px";

export interface AreaTableProps {
  readonly areas: readonly Area[];
  readonly review: BudgetReview;
  readonly preferences: PreferenceSet;
  readonly editingAreaId: string | null;
  readonly onEdit: (areaId: string | null) => void;
  readonly declare: Write<AreaPreferenceEdit>;
  readonly remove: Write<AreaPreferenceRemoval>;
}

/** The signed deviation in percentage points, or a dash where the week has no target to compare with. */
export function deviationText(
  category: ReviewCategory | undefined,
  discretionary: number | null,
): string {
  if (category === undefined || category.targetMinutes === null) return NOTHING;
  const points =
    shareOf(category.actualMinutes, discretionary) - shareOf(category.targetMinutes, discretionary);
  const sign = points > 0 ? "+" : points < 0 ? MINUS_SIGN : "";
  return `${sign}${asPoints(Math.abs(points))}`;
}

/* Built outside the component: a cell is a function the table CALLS per row rather than an element it mounts,
 * so it is not a component, and defining one inside a component reads to a linter as a nested component whose
 * subtree would remount. */
function columnsFor({
  areas,
  review,
  preferences,
  editingAreaId,
  onEdit,
  declare,
  remove,
}: AreaTableProps): readonly TableColumn<Area>[] {
  const byArea = new Map(review.categories.map((category) => [category.areaId, category]));
  const nameOf = new Map(areas.map((area) => [area.id, area.name]));

  return [
    {
      key: "area",
      header: "Area",
      width: { weight: 1 },
      cell: (area) => <AreaChip pigment={areaPigment(area.pigmentIndex)} name={area.name} />,
    },
    {
      key: "parent",
      header: "Parent",
      width: PARENT_W,
      cell: (area) => (area.parentId === null ? NOTHING : (nameOf.get(area.parentId) ?? NOTHING)),
    },
    {
      key: "floor",
      header: "Floor / wk",
      width: FLOOR_W,
      measure: "figure",
      cell: (area) => asFloor(area.floorHours),
    },
    {
      key: "share",
      header: "Share of remainder",
      width: SHARE_W,
      measure: "figure",
      cell: (area) => (area.budgetPercent === null ? NOTHING : asWholePercent(area.budgetPercent)),
    },
    {
      key: "this-week",
      header: "This week",
      width: THIS_WEEK_W,
      measure: "figure",
      cell: (area) => hoursOf(byArea.get(area.id)),
    },
    {
      key: "deviation",
      header: "Deviation",
      width: DEVIATION_W,
      measure: "figure",
      cell: (area) => deviationText(byArea.get(area.id), review.discretionaryMinutes),
    },
    {
      key: "preference",
      header: "Preference",
      width: PREFERENCE_W,
      cell: (area) => (
        <PreferenceCell
          areaId={area.id}
          areaName={area.name}
          preference={preferences[area.id]}
          isEditing={editingAreaId === area.id}
          onEdit={onEdit}
          declare={declare}
          remove={remove}
        />
      ),
    },
  ];
}

export function AreaTable(props: AreaTableProps) {
  return (
    <Table
      columns={columnsFor(props)}
      rows={props.areas}
      rowKey={(area) => area.id}
      caption="Every Area, its budget, what it held this week, and when its work should happen"
      countLabel={(count) => `${count} ${count === 1 ? "Area" : "Areas"}`}
    />
  );
}
