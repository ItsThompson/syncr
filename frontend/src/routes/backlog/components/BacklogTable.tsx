/* THE BACKLOG TABLE. The kit's `Table`, given the columns this screen draws and the standing each row carries.
 *
 * THE ROWS ARRIVE IN ORDER. `Table` holds no comparison of its own, and neither does this file: which order a
 * sort asks for is `../order.ts`, applied once between the read and the draw, so nothing here branches on which
 * column the rows run by.
 *
 * THE STANDING IS TWO STATES AND NOT A COLUMN. Overdue takes the left rule and at risk takes the mark, one
 * channel each, so a row carrying both says both. Whether a task is at risk is read from the row the api sent;
 * whether it is overdue is a comparison against the instant this screen was drawn at. */

import { Table, type TableSort } from "../../../ui/domain";
import type { BacklogTask } from "../../../api/hooks/useBacklog";
import { backlogColumns } from "../columns";
import { footerReading } from "../labels";
import { standingOf } from "../standing";
import type { BacklogArea } from "../useBacklogScreen";

export interface BacklogTableProps {
  readonly tasks: readonly BacklogTask[];
  readonly areas: ReadonlyMap<string, BacklogArea>;
  readonly sort: TableSort;
  readonly onSortChange: (next: TableSort) => void;
  /** The reader's own home zone, which is what a deadline is read in. */
  readonly zone: string;
  /** The instant the screen was drawn at, which is what makes a deadline overdue. */
  readonly nowMs: number;
  readonly onComplete: (taskId: string) => void;
}

export function BacklogTable({
  tasks,
  areas,
  sort,
  onSortChange,
  zone,
  nowMs,
  onComplete,
}: BacklogTableProps) {
  return (
    <Table
      caption="The backlog"
      columns={backlogColumns({ areas, zone, onComplete })}
      countLabel={footerReading}
      onSortChange={onSortChange}
      rowKey={(task) => task.id}
      rows={tasks}
      sort={sort}
      standing={(task) => standingOf(task, nowMs)}
    />
  );
}
