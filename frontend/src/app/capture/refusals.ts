/* WHAT THE FORM HAS TO SAY, AND WHERE ON IT EACH THING LANDS.
 *
 * A 422 NAMES THE MEMBERS IT REFUSES, and those belong at the rows they name: a reader fixing a title should
 * read the reason under the title. What is left over is the refusal's own sentence, which belongs at inline
 * volume inside the dialog, because a request that never arrived or a 409 names no member at all.
 *
 * AMBER RATHER THAN OXIDE FOR A REFUSAL: nothing is broken. The api applied nothing, the draft still reads as
 * the reader left it, and the repair is the form already open in front of them.
 *
 * THE FIELD NAMES ARE THE API's. The wire spells a member the way the request shape spells it, and the draft
 * holds the same names for the same reason, so a refusal naming `minChunkMinutes` reaches the minimum-chunk row
 * without a translation table. A member the draft has no row for is left in the refusal's own sentence rather
 * than dropped, which is what keeps a refusal about `projectId` readable on a form with no project field.
 *
 * WHICH OPENING A REFUSAL BELONGS TO IS NOT DECIDED HERE. The host compares the generation and hands over the
 * problem only when it is this form's, because a refusal for a draft the reader discarded would otherwise state
 * a member of a task that no longer exists. */

import type { Notice } from "../../ui/domain";
import type { Problem } from "../../contract";
import type { CaptureDraft, DraftRefusals } from "./draft";

/** Every member of the draft, so a field error can be told from one the form has no row for. */
const ROWS: readonly (keyof CaptureDraft)[] = [
  "title",
  "areaId",
  "estimateMinutes",
  "minChunkMinutes",
  "deadline",
  "priority",
  "splittable",
];

function isRow(field: string): field is keyof CaptureDraft {
  return ROWS.some((row) => row === field);
}

/** The api's field errors, keyed by the row each one belongs to. */
export function refusalsFrom(problem: Problem | null): DraftRefusals {
  if (problem === null) return {};
  const refusals: DraftRefusals = {};
  for (const error of problem.errors ?? []) {
    if (isRow(error.field)) refusals[error.field] = error.message;
  }
  return refusals;
}

/** A refusal the api answered with, at inline volume inside the dialog. */
export function captureRefusedNotice(problem: Problem): Notice {
  const unplaced = (problem.errors ?? [])
    .filter((error) => !isRow(error.field))
    .map((error) => `${error.field} ${error.message}.`);

  return {
    id: "capture-refused",
    volume: "inline",
    pigment: "amber",
    title: problem.title,
    detail: [...unplaced, problem.detail].join(" "),
    unavailable: [],
    stillWorks: ["this draft, which still reads as you left it", "capturing it again"],
    since: null,
    action: null,
    scope: { screen: "backlog" },
  };
}

/**
 * A send this form does not own is still open, so this one cannot be sent yet.
 *
 * The reader reaches it by dismissing the form while a capture was in flight and opening it again. The control
 * is disabled and this is the sentence that says why, because a disabled control with no reason is a control
 * that appears broken. INFORMATIONAL: nothing is wrong, and the request that is open will be applied.
 *
 * A count that changes is how this product reports progress and there is no count here, so it says in words
 * what it is waiting for, which is what every pending surface in this kit does instead of spinning.
 */
export function sendStillOpenNotice(): Notice {
  return {
    id: "capture-send-open",
    volume: "inline",
    pigment: "info",
    title: "A capture is still being sent",
    detail:
      "The task you sent has not been answered for yet, and it will be captured whatever this form does. " +
      "This one can be sent as soon as that one lands.",
    unavailable: [],
    stillWorks: ["filling this form in", "dismissing it and coming back"],
    since: null,
    action: null,
    scope: { screen: "backlog" },
  };
}
