/* THE BANNER A WRITE RAISES WHEN IT FAILS WITH NOTHING LEFT TO SAY SO ON, COMPOSED ONCE FOR ALL OF THEM.
 *
 * ONE MODULE FOR EVERY WRITE OF THIS KIND, so the second one cannot answer the same condition differently. A
 * write belongs here when three things hold: it is unsafe, the api refused it, and the surface that asked for it
 * is gone by the time the answer arrives. Capture is the first, because its dialog can be dismissed while the
 * request is still open. A write whose form is still on screen states its refusal in that form, at inline volume,
 * and raises nothing from here.
 *
 * A CAPTURE IS TWO WRITES AND EACH HAS ITS OWN SENTENCE, because they leave two different worlds behind: a
 * refused capture leaves nothing, and a refused preference leaves a task in the reader's list with no preferred
 * time on it. `notSavedNotice` maps the pair TOTALLY, so a third write on this path cannot be added without
 * saying what a reader is told when it fails.
 *
 * OXIDE, BECAUSE A DURABLE WRITE DID NOT HAPPEN. It is the pigment the two comparable conditions already take,
 * the write target's token expiring and a projection that stopped. Amber says attention is needed with nothing
 * broken, which is what a refusal inside a form the reader can still fix is.
 *
 * THIS REPORTS A REFUSAL AND CANNOT REPORT A LOST WRITE. The writing layer reads the api's answer and no further:
 * a 2xx is a success from here whatever row came back with it, so a write that landed as another resource's row
 * is a silence no notice on this side can break.
 *
 * THE SURVIVING CAPABILITIES ARE A NAMED CONSTANT rather than a table keyed by write, because the audit that
 * reads every notice out of this tree's own source, `src/testing/noticeLiterals.ts`, follows an identifier to an
 * array in the same module and reports anything else as a list nobody has read. */

import type { CaptureWrite } from "../../api/hooks/useTaskCapture";
import type { Problem } from "../../contract";
import type { BannerNotice } from "./clientNotices";

/** What survives a capture the api refused: the reader's own list, and the gesture that failed. */
const CAPTURE_STILL_WORKS = [
  "your backlog, which is unchanged",
  "capturing the task again",
] as const;

/** What survives a preferred window the api refused: the task itself, and the plan it is now waiting in. */
const PREFERENCE_STILL_WORKS = [
  "the task, which is in your backlog",
  "the next plan, which will place it without a preferred time",
] as const;

/**
 * A capture the api refused after the form that asked for it had gone.
 *
 * THE TITLE THE READER TYPED IS NOT RECOVERABLE, and the sentence says so: the draft is discarded with the
 * opening it belonged to, so "capture it again" means typing it again rather than pressing send again. Saying
 * that plainly is what stops a reader looking for a form syncr is holding for them.
 */
export function captureNotSavedNotice(problem: Problem): BannerNotice {
  return {
    id: "capture-not-saved",
    volume: "banner",
    pigment: "oxide",
    title: "A task you captured was not saved",
    detail:
      `${problem.detail} The title you typed was not saved either, ` +
      "so capturing the task again means typing it again.",
    unavailable: [],
    stillWorks: CAPTURE_STILL_WORKS,
    since: null,
    action: null,
    scope: null,
  };
}

/**
 * A task that landed whose own preferred time did not.
 *
 * THE TASK IS NOT LOST AND THE FIRST CLAUSE SAYS SO, because the reader's question on reading a failure after a
 * capture is whether they have to type it again. They do not: the window is the only thing missing, the work is
 * in the list, and the next plan places it with its Area's preferred time or with none.
 */
export function preferredTimeNotSavedNotice(problem: Problem): BannerNotice {
  return {
    id: "capture-preferred-time-not-saved",
    volume: "banner",
    pigment: "oxide",
    title: "A task was saved without the time you captured it from",
    detail:
      `The task itself was saved. Its own preferred time was not: ${problem.detail} ` +
      "Nothing you typed was lost, and the task will be planned as the rest of its Area is.",
    unavailable: [],
    stillWorks: PREFERENCE_STILL_WORKS,
    since: null,
    action: null,
    scope: null,
  };
}

/** The banner for whichever of a capture's two writes the api refused. */
const NOT_SAVED: Readonly<Record<CaptureWrite, (problem: Problem) => BannerNotice>> = {
  task: captureNotSavedNotice,
  preference: preferredTimeNotSavedNotice,
};

/**
 * What a reader is told when one of a capture's two writes did not land.
 *
 * The map is total over the pair, so the two conditions cannot answer with one sentence between them and a third
 * write on this path is a compile error rather than a silence.
 */
export function notSavedNotice(refused: CaptureWrite, problem: Problem): BannerNotice {
  return NOT_SAVED[refused](problem);
}
