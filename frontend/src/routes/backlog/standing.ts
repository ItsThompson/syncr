/* WHAT MAKES A ROW OVERDUE, AND WHAT MAKES IT AT RISK, WHICH ARE TWO DIFFERENT KINDS OF FACT.
 *
 * OVERDUE IS ARITHMETIC OVER A CLOCK: the deadline is behind now. It has no server field because there is
 * nothing to derive: an instant and a clock are all it takes, and a field would go stale between the read and
 * the render on a screen left open.
 *
 * AT RISK IS THE SERVER'S DETERMINATION AND IS READ, NEVER COMPUTED. A task is at risk when the current week's
 * verdict reports a deadline shortfall naming it, which is the same shortfall the week's verdict panel renders.
 * There is deliberately no comparison of a deadline against a capacity here: a second arithmetic is exactly how
 * a task comes to be at risk on one screen and fine on another, and the figure a client could compute would not
 * be the same one, because the verdict's is net on both sides and clips capacity to now.
 *
 * SO THIS FILE READS ONE FIELD AND COMPARES ONE PAIR OF INSTANTS, and the asymmetry is the point. */

import type { BacklogTask } from "../../api/hooks/useBacklog";
import type { TableRowStanding } from "../../ui/domain";

/** True when the deadline this task carries is behind the instant given. */
export function isOverdue(task: BacklogTask, nowMs: number): boolean {
  if (task.deadline === null) return false;
  const due = Date.parse(task.deadline);
  return !Number.isNaN(due) && due < nowMs;
}

/**
 * The two states a row carries, for the table's own closed-vocabulary attributes.
 *
 * A task that has left the backlog carries neither. An ended task is not overdue, because nothing is owed on
 * it any more, and the server does not mark one at risk for the same reason: the at-risk population is the
 * Area's OPEN tasks. Stated here so a table filtered to completed rows does not draw a run of oxide rules
 * about work that is done.
 */
export function standingOf(task: BacklogTask, nowMs: number): TableRowStanding {
  if (task.status !== "open") return {};
  return { isOverdue: isOverdue(task, nowMs), isAtRisk: task.atRisk };
}
