/* THE COLUMNS THE BACKLOG DRAWS, and the two cells that are controls rather than readings.
 *
 * A MODULE-LEVEL FACTORY RATHER THAN AN ARRAY INSIDE THE COMPONENT. Each cell is a function of a row, and a
 * function returning markup declared inside a component is a component declared during a render: it would be a
 * new type on every draw and React would remount every cell in the table. Built here, they are declared once.
 *
 * THE AREA CELL DRAWS A CHIP AND ITS NAME. Ink is never the whole of what identifies an Area, so the kit
 * refuses a chip without a name at the typecheck. A row whose Area the read has no entry for draws the empty
 * reading rather than a chip with no pigment.
 *
 * THE STANDING IS NOT A COLUMN. Overdue and at risk are states on the row, one channel each, which is why they
 * are absent from this file: `Table` reserves the mark cell and draws them. */

import { AreaChip, type TableColumn } from "../../ui/domain";
import { Button } from "../../ui/primitives";
import type { BacklogTask } from "../../api/hooks/useBacklog";
import { chunkReading, deadlineReading, minutesReading, NOTHING } from "./labels";
import type { BacklogArea } from "./useBacklogScreen";

export interface BacklogColumnsInput {
  /** Each Area's name and its assigned ramp step, so a row can draw a chip that identifies something. */
  readonly areas: ReadonlyMap<string, BacklogArea>;
  /** The reader's own home zone, which is what a deadline is read in. */
  readonly zone: string;
  readonly onComplete: (taskId: string) => void;
}

export function backlogColumns({
  areas,
  zone,
  onComplete,
}: BacklogColumnsInput): readonly TableColumn<BacklogTask>[] {
  return [
    { key: "title", header: "Task", isSortable: true, cell: (task) => task.title },
    {
      key: "area",
      header: "Area",
      isSortable: true,
      cell: (task) => {
        const area = areas.get(task.areaId);
        if (area === undefined) return NOTHING;
        return <AreaChip name={area.name} pigment={area.pigment} />;
      },
    },
    {
      key: "deadline",
      header: "Deadline",
      isSortable: true,
      cell: (task) => deadlineReading(task.deadline, zone),
    },
    {
      key: "remaining",
      header: "Remaining",
      measure: "figure",
      isSortable: true,
      cell: (task) => minutesReading(task.remainingMinutes),
    },
    { key: "priority", header: "Priority", isSortable: true, cell: (task) => task.priority },
    { key: "chunk", header: "Chunk", cell: (task) => chunkReading(task) },
    {
      key: "settle",
      header: "Done",
      cell: (task) => {
        if (task.status !== "open") return task.status;
        return (
          <Button onClick={() => onComplete(task.id)} rank="tertiary" size="sm">
            Complete
          </Button>
        );
      },
    },
  ];
}
