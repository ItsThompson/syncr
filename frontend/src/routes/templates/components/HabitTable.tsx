/* The habits, with both derivations rendered beside each one and neither settable.
 *
 * THE CURSOR COLUMN IS A READING, NOT A CONTROL, and the table is where that has to be visible: the cursor is
 * a projection of the confirmed outcome log, so it carries its own provenance sentence and there is no route
 * that sets one. A habit that does not rotate shows no cursor at all rather than a zero or a dash-shaped
 * placeholder for a value it does not have.
 *
 * THE DEBT FIGURE IS THE OUTSTANDING COUNT AGAINST ITS CAP, because the cap is what makes the figure mean
 * anything: `2 of 4` says two occurrences are owed and two more misses would be forgiven rather than added.
 *
 * SELECTING IS A BUTTON IN THE CELL, for the same reason as the shape list: a row that answers a click without
 * being a control cannot be reached from the keyboard. */

import { AreaChip, Table, areaPigment, type TableColumn } from "../../../ui/domain";
import { Button } from "../../../ui/primitives";
import { cadenceLabel, habitDurationLabel } from "../labels";
import { areaOf } from "../naming";
import type { Area } from "../../../api/hooks/useAreas";
import type { Habit } from "../../../api/hooks/useHabits";

export interface HabitTableProps {
  readonly habits: readonly Habit[];
  readonly areas: readonly Area[];
  readonly selectedId: string | null;
  readonly onSelect: (habitId: string) => void;
}

/** U+2014, which is the width of the column's own dash rather than a hyphen standing in for one. */
const NOTHING = "\u2014";

/* Built outside the component: a cell is a function the table CALLS per row rather than an element it mounts,
 * so it is not a component, and defining one inside a component reads to a linter as a nested component whose
 * subtree would remount. */
function columnsFor({
  areas,
  selectedId,
  onSelect,
}: Omit<HabitTableProps, "habits">): readonly TableColumn<Habit>[] {
  return [
    {
      key: "title",
      header: "Habit",
      cell: (habit) => (
        <Button
          rank={habit.id === selectedId ? "secondary" : "quiet"}
          size="sm"
          onClick={() => onSelect(habit.id)}
        >
          {habit.title}
        </Button>
      ),
    },
    {
      key: "area",
      header: "Area",
      cell: (habit) => {
        const area = areaOf(areas, habit.areaId);
        if (area === null) return "an Area you no longer have";
        return <AreaChip name={area.name} pigment={areaPigment(area.pigmentIndex)} />;
      },
    },
    { key: "cadence", header: "Cadence", cell: (habit) => cadenceLabel(habit.cadence) },
    {
      key: "duration",
      header: "Duration",
      measure: "figure",
      cell: (habit) => habitDurationLabel(habit),
    },
    { key: "missPolicy", header: "On miss", cell: (habit) => habit.missPolicy },
    { key: "bindingSource", header: "Binding", cell: (habit) => habit.bindingSource },
    {
      key: "debt",
      header: "Debt",
      measure: "figure",
      cell: (habit) => `${habit.debt.outstanding} of ${habit.debt.cap}`,
    },
    {
      key: "cursor",
      header: "Cursor",
      /* ONE LINE, WHICH IS THE ROW'S HEIGHT. The cell states the variant and that it is derived, which is the
       * rendered sheet's own `Legs \u00B7 derived`: a second line inside a cell grows the row past the 28px the
       * table is pitched at, and a table whose rows vary in height is not the dense surface it exists to be.
       * The cursor's whole provenance sentence is rendered beside the editor, where there is room for it. */
      cell: (habit) => (habit.cursor === null ? NOTHING : `${habit.cursor.variant} \u00B7 derived`),
    },
  ];
}

export function HabitTable({ habits, areas, selectedId, onSelect }: HabitTableProps) {
  return (
    <Table
      columns={columnsFor({ areas, selectedId, onSelect })}
      rows={habits}
      rowKey={(habit) => habit.id}
      caption="Habits, with the rotation cursor and the debt figure as read-only derivations"
      countLabel={(count) => `${count} habits \u00B7 the cursor and the debt figure are derived`}
    />
  );
}
