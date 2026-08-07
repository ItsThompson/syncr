/* WHAT THE API'S REFUSAL SAYS, AND WHERE ON THE FORM IT LANDS.
 *
 * TWO SURFACES FOR ONE REFUSAL, and they say different things. A 422 names the members it refuses, and those
 * belong at the rows they name: a reader fixing a title should read the reason under the title. What is left
 * over is the refusal's own sentence, which belongs at inline volume inside the dialog, because a request that
 * never arrived or a 409 names no member at all.
 *
 * THE FIELD NAMES ARE THE API's. The wire spells a member the way the request shape spells it, and the draft
 * holds the same names for the same reason, so a refusal naming `minChunkMinutes` reaches the minimum-chunk row
 * without a translation table. A member the draft has no row for is left in the refusal's own sentence rather
 * than dropped, which is what keeps a refusal about `projectId` readable on a form with no project field. */

import type { Notice } from "../../../ui/domain";
import type { Problem } from "../../../contract";
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

/**
 * The refusal as a notice, at inline volume inside the dialog.
 *
 * Amber rather than oxide: nothing is broken. The api applied nothing, the draft still reads as the reader left
 * it, and the repair is the form already open in front of them. Members the form has no row for are named in
 * the sentence, so a refusal is never silent even when it is about a field this dialog does not draw.
 */
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
