/* One day shape's entries, in the order the day runs.
 *
 * THE COLUMNS AND THEIR ORDER ARE `docs/design/screens.html`'s: target, kind, entry, Area, duration, flex.
 *
 * A SLOT NAMES NO CONTENT AND SAYS SO. `bound at plan time` is the sheet's own wording, and it is the whole
 * point of a slot: an Area and a duration, with the content chosen when the week is planned, which is what
 * makes the calendar say which topic matters this week rather than repeating one title.
 *
 * A CONCRETE ENTRY WITH NO AREA READS AS `frame`, because a routine carries no Area at all: the frame defines
 * how much time exists rather than consuming a budget. */

import { AreaChip, Table, areaPigment, type TableColumn } from "../../../ui/domain";
import { flexLabel, minutesLabel } from "../labels";
import { areaOf, bindingNameOf } from "../naming";
import type { Area } from "../../../api/hooks/useAreas";
import type { Habit } from "../../../api/hooks/useHabits";
import type { Routine } from "../../../api/hooks/useRoutines";
import type { TemplateEntry } from "../../../api/hooks/useTemplates";

export interface EntryTableProps {
  readonly entries: readonly TemplateEntry[];
  readonly areas: readonly Area[];
  readonly routines: readonly Routine[];
  readonly habits: readonly Habit[];
}

/* Built outside the component: a cell is a function the table CALLS per row rather than an element it mounts,
 * so it is not a component, and defining one inside a component reads to a linter as a nested component whose
 * subtree would remount. */
function columnsFor({
  areas,
  routines,
  habits,
}: Omit<EntryTableProps, "entries">): readonly TableColumn<TemplateEntry>[] {
  return [
    { key: "targetTime", header: "Target", measure: "figure", cell: (entry) => entry.targetTime },
    { key: "kind", header: "Kind", cell: (entry) => entry.kind },
    {
      key: "entry",
      header: "Entry",
      cell: (entry) => {
        if (entry.kind === "slot") return "bound at plan time";
        return bindingNameOf(entry, routines, habits) ?? "content you no longer have";
      },
    },
    {
      key: "area",
      header: "Area",
      cell: (entry) => {
        const area = areaOf(areas, entry.areaId);
        if (area === null) return entry.areaId === null ? "frame" : "an Area you no longer have";
        return <AreaChip name={area.name} pigment={areaPigment(area.pigmentIndex)} />;
      },
    },
    {
      key: "duration",
      header: "Duration",
      measure: "figure",
      cell: (entry) => minutesLabel(entry.durationMinutes),
    },
    {
      key: "flex",
      header: "Flex",
      measure: "figure",
      cell: (entry) => flexLabel(entry.flexBandMinutes),
    },
  ];
}

export function EntryTable({ entries, areas, routines, habits }: EntryTableProps) {
  return (
    <Table
      columns={columnsFor({ areas, routines, habits })}
      rows={entries}
      rowKey={(entry) => entry.id}
      caption="The entries this day shape holds"
      countLabel={(count) => `${count} entries \u00B7 every entry is fixed by derivation`}
    />
  );
}
