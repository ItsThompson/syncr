/* THE TWO NOTICES THIS SCREEN RAISES, each at the volume and pigment the shell's table assigns it.
 *
 *   a completion that landed   panel, verdigris. The row it concerned is gone, so there is no row to sit
 *                              beside, and the thing it has to say is about the next solve rather than about
 *                              the task: the blocks bound to it become empty space, which is a fill change and
 *                              therefore auto-applies. Verdigris is the one pigment for a confirmation and is
 *                              spent sparingly
 *   a refused completion       panel, amber. The api applied nothing, the table still reads as it did, and the
 *                              repair is the control the reader already has
 *
 * A COMPLETION IS PANEL VOLUME AND NOT INLINE for a structural reason rather than a stylistic one: volume 1 is
 * inline at the block or row it concerns, and completing a task removes its row. A notice with no row to sit at
 * has no inline position, so it takes the next volume up.
 *
 * EVERY NOTICE NAMES WHAT STILL WORKS, which the kit's type refuses to let a caller leave empty. */

import type { Notice } from "../../ui/domain";
import type { Problem } from "../../contract";

/** The api's own sentence, with the members it named first: a 422 says which figure to change. */
function detailOf(problem: Problem): string {
  const members = (problem.errors ?? []).map((error) => `${error.field} ${error.message}.`);
  return [...members, problem.detail].join(" ");
}

/**
 * What completing a task did, and what happens to the blocks that were planned for it.
 *
 * The sentence names the consequence rather than the act, because the act is already visible: the row left the
 * table. What is not visible is that the plan still holds blocks bound to the task, that they become empty
 * space in the next solve, and that the change lands without being approved because a fill change auto-applies.
 */
export function taskCompletedNotice(taskId: string): Notice {
  return {
    id: `task-completed-${taskId}`,
    volume: "panel",
    pigment: "verdigris",
    title: "Task completed",
    detail:
      "It has left solver eligibility and keeps the time already recorded against it, so reports still " +
      "show the work. Any blocks the plan still holds for it become empty space in the next solve, which " +
      "is a fill change and applies without being approved.",
    unavailable: [],
    stillWorks: ["the rest of the backlog", "reading the completed task by asking for that status"],
    since: null,
    action: null,
    scope: { screen: "backlog" },
  };
}

/** A completion the api refused, at the head of the screen the table it concerns is on. */
export function completionRefusedNotice(problem: Problem): Notice {
  return {
    id: "completion-refused",
    volume: "panel",
    pigment: "amber",
    title: problem.title,
    detail: detailOf(problem),
    unavailable: [],
    stillWorks: ["the table, which still reads as it did", "completing the task again"],
    since: null,
    action: null,
    scope: { screen: "backlog" },
  };
}
