/* The day shapes a tenant has declared, and which one the editor is showing.
 *
 * THE ROW STATES A COUNT, NOT THE ENTRIES. That is the list response's own shape: a shape's entries are read
 * per shape, so the count is what the list can say and it is what a reader picking a shape needs.
 *
 * SELECTING IS A BUTTON IN THE CELL rather than a click handler on the row. A row that responds to a click
 * without being a control is unreachable by keyboard, and the whole product is keyboard-first. The selected
 * shape's button takes the secondary rank and the others the quiet one, so the choice is visible in the list
 * as well as in the panel beside it. */

import { Table, type TableColumn } from "../../../ui/domain";
import { Button } from "../../../ui/primitives";
import type { DayShapeSummary, DayType } from "../../../api/hooks/useTemplates";

export interface ShapeListProps {
  readonly shapes: readonly DayShapeSummary[];
  readonly dayTypes: readonly DayType[];
  readonly selectedId: string | null;
  readonly onSelect: (templateId: string) => void;
}

/* The columns are built outside the component, which is not a style choice: a cell is a function the table
 * CALLS per row rather than an element it mounts, so it is not a component, and defining one inside a component
 * reads to a linter as a nested component whose subtree would remount. Built here, the shape of a row is a pure
 * function of what a row needs to know. */
function columnsFor({
  dayTypes,
  selectedId,
  onSelect,
}: Omit<ShapeListProps, "shapes">): readonly TableColumn<DayShapeSummary>[] {
  return [
    {
      key: "name",
      header: "Shape",
      cell: (shape) => (
        <Button
          rank={shape.id === selectedId ? "secondary" : "quiet"}
          size="sm"
          onClick={() => onSelect(shape.id)}
        >
          {shape.name}
        </Button>
      ),
    },
    {
      key: "dayType",
      header: "Day type",
      cell: (shape) =>
        dayTypes.find((dayType) => dayType.id === shape.dayTypeId)?.name ??
        "a day type you no longer have",
    },
    {
      key: "entryCount",
      header: "Entries",
      measure: "figure",
      cell: (shape) => shape.entryCount,
    },
  ];
}

export function ShapeList({ shapes, dayTypes, selectedId, onSelect }: ShapeListProps) {
  return (
    <Table
      columns={columnsFor({ dayTypes, selectedId, onSelect })}
      rows={shapes}
      rowKey={(shape) => shape.id}
      caption="Day shapes"
      countLabel={(count) => `${count} declared`}
    />
  );
}
