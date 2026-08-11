/* THE BANNER A WRITE RAISES WHEN IT FAILS WITH NOTHING LEFT TO SAY SO ON, COMPOSED ONCE FOR ALL OF THEM.
 *
 * ONE MODULE FOR EVERY WRITE OF THIS KIND, so the second one cannot answer the same condition differently. A
 * write belongs here when three things hold: it is unsafe, the api refused it, and the surface that asked for it
 * is gone by the time the answer arrives. Capture is the first, because its dialog can be dismissed while the
 * request is still open. A write whose form is still on screen states its refusal in that form, at inline volume,
 * and raises nothing from here.
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

import type { BannerNotice } from "./clientNotices";
import type { Problem } from "../../contract";

/** What survives a capture the api refused: the reader's own list, and the gesture that failed. */
const CAPTURE_STILL_WORKS = [
  "your backlog, which is unchanged",
  "capturing the task again",
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
