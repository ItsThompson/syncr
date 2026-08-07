/* THE ORDER THE TABLE DRAWS, AND WHY IT IS DECIDED HERE RATHER THAN BY THE ROUTE.
 *
 * `GET /api/v1/tasks` serves the backlog oldest first, and its repository states why: the order a backlog is
 * READ in needs a deadline, a priority and the verdict's shortfalls to decide, so persistence owes only an
 * order that does not change between two identical reads. The screen is what has all three, so the screen
 * orders. The FILTERS are the query's, because each of them narrows what the server would have to send and one
 * of them, the at-risk narrowing, is a determination no client can reproduce.
 *
 * SORTING IS THEREFORE A FACT ABOUT THE READ AND NOT ABOUT THE RENDERING. `Table` draws the rows it is given in
 * the order it is given them and holds no comparison of its own; this module turns a column and a direction
 * into one, and the screen applies it once between the read and the draw. Nothing downstream branches on which
 * column is ordered by.
 *
 * A DEADLINE-BEARING TASK SORTS BEFORE ONE WITH NO DEADLINE, in both directions. A null is not a value at one
 * end of the range: a task with no deadline is not due first and is not due last, it is not due, so it sits
 * after every task that is, whichever way the column runs. Reversing that would put the rows a reader sorted by
 * deadline in order to see at the bottom of the table. */

import type { BacklogTask } from "../../api/hooks/useBacklog";
import type { TableSort } from "../../ui/domain";

/** The columns the backlog can be ordered by. A column absent from here has no sortable header. */
export const BACKLOG_COLUMNS = ["title", "area", "deadline", "remaining", "priority"] as const;

export type BacklogColumn = (typeof BACKLOG_COLUMNS)[number];

/** Least preferred first, which is the objective's own order rather than the alphabet's. */
const PRIORITY_ORDER = ["low", "normal", "high", "urgent"] as const;

export const DEFAULT_SORT: TableSort = { key: "deadline", direction: "ascending" };

/** How a row compares on one column, before the direction is applied. */
type Comparison = (left: BacklogTask, right: BacklogTask) => number;

function byText(of: (task: BacklogTask) => string): Comparison {
  return (left, right) => of(left).localeCompare(of(right));
}

/** A null deadline sorts last whichever way the column runs, so the direction is applied after it. */
function byDeadline(left: BacklogTask, right: BacklogTask): number {
  if (left.deadline === null || right.deadline === null) return 0;
  return Date.parse(left.deadline) - Date.parse(right.deadline);
}

function byPriority(left: BacklogTask, right: BacklogTask): number {
  return PRIORITY_ORDER.indexOf(left.priority) - PRIORITY_ORDER.indexOf(right.priority);
}

/**
 * The comparison each column carries, keyed by the column's own key.
 *
 * `area` compares the NAME a reader sees rather than the identifier, which is why the caller supplies the
 * naming: the wire carries an Area's id on a task and the name lives on the Area list, so a comparison over
 * ids would order the column by something invisible.
 */
function comparisons(areaName: (areaId: string) => string): Record<BacklogColumn, Comparison> {
  return {
    title: byText((task) => task.title),
    area: byText((task) => areaName(task.areaId)),
    deadline: byDeadline,
    remaining: (left, right) => left.remainingMinutes - right.remainingMinutes,
    priority: byPriority,
  };
}

function isBacklogColumn(key: string): key is BacklogColumn {
  return BACKLOG_COLUMNS.some((column) => column === key);
}

/** A task with no deadline is not due, so it sits after every task that is, in both directions. */
function isUndated(task: BacklogTask): number {
  return task.deadline === null ? 1 : 0;
}

/**
 * The rows in the order a sort asks for, with the tasks that carry no deadline after those that do.
 *
 * A copy, because the read's own array is SWR's cached value and ordering it in place would reorder the cache.
 * The tie-break is the identifier, so two rows that compare equal keep one order between two renders rather
 * than swapping under a reader.
 */
export function ordered(
  tasks: readonly BacklogTask[],
  sort: TableSort,
  areaName: (areaId: string) => string,
): readonly BacklogTask[] {
  if (!isBacklogColumn(sort.key)) return tasks;
  const compare = comparisons(areaName)[sort.key];
  const sign = sort.direction === "ascending" ? 1 : -1;
  const separatesUndated = sort.key === "deadline";

  return [...tasks].toSorted((left, right) => {
    if (separatesUndated && isUndated(left) !== isUndated(right)) {
      return isUndated(left) - isUndated(right);
    }
    const compared = compare(left, right);
    return compared === 0 ? left.id.localeCompare(right.id) : compared * sign;
  });
}
