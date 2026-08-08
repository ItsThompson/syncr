/* THE NOTICES THIS SCREEN RAISES, IN THE WORDS A READER MEETS THEM IN.
 *
 * ONE PLACE, BECAUSE VOLUME IS POSITION. A conflict is a banner and it persists until the overlap is answered; a
 * failed solve is a panel at the head of the screen and the previous plan stays on the grid; a refused pin is a panel
 * too, because it is about the week rather than about one row. None of them is a dialog: level 4 of the ladder does
 * not exist.
 *
 * EVERY NOTICE NAMES WHAT STILL WORKS, and that is a type rule rather than a convention: `stillWorks` is a non-empty
 * tuple, so a notice that says only what broke does not compile. On this screen the answer is nearly always the same
 * one, and it is worth saying plainly: the plan on the grid is the plan of record, and reading it is unaffected.
 *
 * A PENDING PROPOSAL RAISES NOTHING AT ALL. It is visible when the reader looks -- no fill and a dashed outline -- and
 * a notification for it would spend the one channel a conflict needs. */

import type { Notice } from "../../ui/domain";
import type { OperationFailure } from "../../api/hooks/useOperation";
import type { Problem } from "../../contract";

const PLAN_STILL_READS: readonly [string, ...string[]] = [
  "the plan on the grid, which is the plan of record",
];

/** A commitment landed on a planned block. Banner volume, oxide, until it is answered. */
export function conflictNotice(conflictId: string, statement: string, blockId: string): Notice {
  return {
    id: `conflict:${conflictId}`,
    volume: "banner",
    pigment: "oxide",
    title: "A commitment landed on a planned block",
    detail: statement,
    unavailable: [],
    stillWorks: PLAN_STILL_READS,
    since: null,
    action: null,
    scope: { screen: "/week", blockId },
  };
}

/**
 * A solve that produced no plan. Panel volume, oxide, with the previous plan still rendered.
 *
 * THE ATTEMPT COUNT IS PART OF THE SENTENCE, because retries here are bounded and silent otherwise. A retryable
 * failure goes back to the queue as `pending`, so a `failed` status reaching this screen has spent every attempt it
 * was given: saying how many is what tells a reader the difference between bad luck and a week that cannot be
 * solved. It is a count rather than a bar, which is how progress is reported in a product with no motion.
 */
export function solveFailedNotice(failure: OperationFailure): Notice {
  return {
    id: `solve-failed:${failure.operationId}`,
    volume: "panel",
    pigment: "oxide",
    title: "This week's solve produced no plan",
    detail: `${failure.statement} ${attemptsSpent(failure.attempt)}`,
    unavailable: ["a plan that reflects your most recent edits"],
    stillWorks: PLAN_STILL_READS,
    since: null,
    action: null,
    scope: { screen: "/week" },
  };
}

/** The count, in the words a reader would use for it. */
function attemptsSpent(attempt: number): string {
  return attempt === 1
    ? "It was attempted once."
    : `It was attempted ${String(attempt)} times, which is every retry syncr allows it.`;
}

/**
 * A write the api refused. Panel volume, amber: the reader's plan is untouched and the reason is the api's own.
 *
 * THE IDENTITY CARRIES THE WRITE AS WELL AS THE PROBLEM, because five writes on this screen render through one notice
 * list and two of them can be refused with the same problem type: a pin and an approval both answering `409` would
 * otherwise be two notices under one React key. The write is the caller's own word for itself, so the reader also gets
 * a distinguishable one when two notices stand at once.
 */
export function refusedNotice(write: string, problem: Problem): Notice {
  return {
    id: `refused:${write}:${problem.type}`,
    volume: "panel",
    pigment: "amber",
    title: problem.title,
    detail: problem.detail,
    unavailable: [],
    stillWorks: PLAN_STILL_READS,
    since: null,
    action: null,
    scope: { screen: "/week" },
  };
}
