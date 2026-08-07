/* THE FILTERS THE SCREEN HOLDS, AND THE VALUES THE ROUTE SERVES FOR EACH.
 *
 * EVERY ONE OF THE THREE IS A QUERY PARAMETER. Narrowing is therefore a change to the request and to the key it
 * caches under, never a rule the rendering applies: the table draws the rows the read handed back. The at-risk
 * filter is the one that makes this structural rather than stylistic, because at risk is the week verdict's
 * determination and not a field a client can compare, so a screen that narrowed a list it already held would
 * show a header count and a row set that disagree.
 *
 * THE SCREEN OPENS ON THE OPEN TASKS. A backlog is the work outstanding, and the two endings are reachable by
 * asking for them: that is also what makes completing a task remove its row, because a completed task is no
 * longer in what the screen asked for.
 *
 * A SELECT HAS NO EMPTY OPTION, so the absent filter is a named value here and becomes an omitted parameter at
 * the boundary. Each parser answers `undefined` for it and for anything else, which is what a cast would
 * otherwise be. */

import type { BacklogFilters, TaskStatus } from "../../api/hooks/useBacklog";

/** The value that stands for the absent filter in a select. */
export const EVERY = "every";

export const TASK_STATUSES: readonly TaskStatus[] = ["open", "completed", "dropped"];

/** What the screen reads before a reader narrows anything: the work outstanding. */
export const DEFAULT_FILTERS: BacklogFilters = { status: "open" };

/** The Area a select answered with, or the absent filter. */
export function areaFilterOf(value: string): string | undefined {
  return value === EVERY ? undefined : value;
}

/** The status a select answered with, or the absent filter for anything outside the vocabulary. */
export function statusFilterOf(value: string): TaskStatus | undefined {
  return TASK_STATUSES.find((status) => status === value);
}

/**
 * The standing a select answered with: the marked rows, the rest, or the absent filter.
 *
 * Three values rather than a boolean, because the absent filter and `false` are two different questions: one
 * asks for every row and the other asks for the rows this week's verdict does not name.
 */
export function atRiskFilterOf(value: string): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

/** What a select shows for a filter that is not set. */
export function selectedValue(filter: string | boolean | undefined): string {
  return filter === undefined ? EVERY : String(filter);
}
