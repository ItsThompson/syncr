/* The anchor types, in the order the rules evaluate, and the controls that change that order.
 *
 * THE FIRST SIX COLUMNS ARE `docs/design/screens.html`'s, in its order: type, match, pre, transit, post,
 * forbids after. The seventh is appended rather than inserted, because the sheet renders no reordering control
 * at all and the six it does render are compared across rows.
 *
 * `PRE` IS THE LEAD, NOT THE DURATION, which is the sheet's own reading: an interview's `6h` is how long before
 * the commitment prep starts, and its thirty minutes of prep is a member the editor exposes. A lead is what a
 * reader compares down this column, because it is what decides where in the day the shadow lands.
 *
 * ROWS ARE NEVER RE-SORTED HERE. The order is the resource's own state and the first match wins, so ordering
 * this table by name would answer the one question the order settles with the wrong answer. */

import { Table, type TableColumn } from "../../../ui/domain";
import { Button } from "../../../ui/primitives";
import { POST_SCOPE_LABELS, matchLabel, minutesLabel } from "../labels";
import { areaOf } from "../naming";
import type { Area } from "../../../api/hooks/useAreas";
import type { AnchorType } from "../../../api/hooks/useAnchorTypes";
import type { CalendarSource } from "../../../api/hooks/useCalendarSources";

export interface AnchorTypeTableProps {
  readonly types: readonly AnchorType[];
  readonly areas: readonly Area[];
  readonly sources: readonly CalendarSource[];
  readonly selectedId: string | null;
  readonly onSelect: (anchorTypeId: string) => void;
  readonly onMoveEarlier: (anchorTypeId: string) => void;
  readonly onMoveLater: (anchorTypeId: string) => void;
}

/* Built outside the component: a cell is a function the table CALLS per row rather than an element it mounts,
 * so it is not a component, and defining one inside a component reads to a linter as a nested component whose
 * subtree would remount. */
function columnsFor({
  types,
  areas,
  sources,
  selectedId,
  onSelect,
  onMoveEarlier,
  onMoveLater,
}: AnchorTypeTableProps): readonly TableColumn<AnchorType>[] {
  const sourceNameOf = (type: AnchorType): string | null =>
    sources.find((source) => source.id === type.matchSourceId)?.displayName ?? null;

  return [
    {
      key: "name",
      header: "Type",
      cell: (type) => (
        <Button
          rank={type.id === selectedId ? "secondary" : "quiet"}
          size="sm"
          onClick={() => onSelect(type.id)}
        >
          {type.name}
        </Button>
      ),
    },
    { key: "match", header: "Match", cell: (type) => matchLabel(type, sourceNameOf(type)) },
    {
      key: "pre",
      header: "Pre",
      measure: "figure",
      cell: (type) => minutesLabel(type.prepLeadMinutes),
    },
    {
      key: "transit",
      header: "Transit",
      measure: "figure",
      cell: (type) => minutesLabel(type.transitDurationMinutes),
    },
    {
      key: "post",
      header: "Post",
      measure: "figure",
      cell: (type) => minutesLabel(type.postBufferMinutes),
    },
    {
      key: "forbids",
      header: "Forbids after",
      cell: (type) => {
        if (type.postScope !== "areas") return POST_SCOPE_LABELS[type.postScope];
        return type.forbiddenAreaIds
          .map((areaId) => areaOf(areas, areaId)?.name ?? "an Area you no longer have")
          .join(", ");
      },
    },
    {
      key: "order",
      header: "Order",
      cell: (type) => (
        <span className="flex gap-1">
          <Button
            rank="quiet"
            size="sm"
            label={`evaluate ${type.name} earlier`}
            isDisabled={types.at(0)?.id === type.id}
            onClick={() => onMoveEarlier(type.id)}
          >
            earlier
          </Button>
          <Button
            rank="quiet"
            size="sm"
            label={`evaluate ${type.name} later`}
            isDisabled={types.at(-1)?.id === type.id}
            onClick={() => onMoveLater(type.id)}
          >
            later
          </Button>
        </span>
      ),
    },
  ];
}

export function AnchorTypeTable(props: AnchorTypeTableProps) {
  return (
    <Table
      columns={columnsFor(props)}
      rows={props.types}
      rowKey={(type) => type.id}
      caption="Anchor types, in the order the rules evaluate"
      countLabel={(count) => `${count} types \u00B7 rules evaluate in order, first match wins`}
    />
  );
}
