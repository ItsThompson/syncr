/* ONE OPENING OF THE CAPTURE DIALOG, AND THE THREE MOVES IT MAKES.
 *
 * A DIALOG AND A REQUEST ARE TWO LIFETIMES, and every defect this state has carried came from conflating them.
 * The DIALOG is one opening: its draft, where focus returns, and which refusal belongs to it. The REQUEST is one
 * send: it begins when the lock is taken and ends when the api answers, whatever the reader does to the dialog in
 * between. `generation` is what says which opening a send belongs to, and it is why these moves are pure
 * functions of the state and the answer rather than of whatever the host is rendering when the answer lands.
 *
 * THE LOCK IS NOT HERE. It belongs to the request rather than to the opening, so it lives with the host that
 * sends: a dismiss must not touch it, and nothing in this module can.
 *
 * ONE MOVE PER THING THAT CAN HAPPEN TO AN OPENING: it opens, it closes, or a send it started answers. Keeping
 * them together is what makes the four outcomes of `stateAfter` readable beside the two the other moves have,
 * and it is what makes them assertable without a rendered dialog. */

import type { CaptureWrite, CaptureOutcome } from "../../api/hooks/useTaskCapture";
import type { CaptureOpening } from "./captureContext";
import type { CaptureWindow } from "./preferredWindow";
import { draftFrom, type CaptureDraft } from "./draft";

/** One opening of the dialog: what it holds, where it came from, and which refusal is its own. */
export interface CaptureState {
  readonly isOpen: boolean;
  readonly draft: CaptureDraft;
  /**
   * The element focus returns to on close.
   *
   * READ AT THE MOMENT THE OPEN IS DECIDED, which is inside the keydown or the click that asked for it: that is
   * the last instant at which `document.activeElement` is still where the reader was. One render later the
   * dialog has the focus and the answer is gone. So it arrives here resolved, from the handler that read it.
   */
  readonly returnFocusTo: HTMLElement | null;
  /**
   * The stretch of time this opening's work should prefer, or null where the caller named none.
   *
   * Held beside the draft rather than in it, because the capture request carries no preference member: what the
   * form does with it is state it, and writing it is a second request against the task the first one creates.
   */
  readonly preferredWindow: CaptureWindow | null;
  /**
   * Which opening this is. Bumped on every open and every close.
   *
   * A send carries the number it started under and compares it before it changes anything, so a dismiss or a
   * reopen makes a resolved send inert rather than letting it act on a dialog that is no longer the one it
   * started with.
   */
  readonly generation: number;
  /** The opening the last refusal belongs to, so a refusal cannot land on a draft that replaced it. */
  readonly refusedAt: number | null;
  /**
   * The write of this opening's whose refusal no form is left to state, or null when there is none.
   *
   * It is held here rather than beside the request because the answer belongs to whichever opening was current
   * when it arrived, and that is what `generation` says: the comparison that keeps a refusal off a draft it is
   * not about is the one that says the refusal has no draft at all. WHICH write is named rather than just that
   * one failed, because a refused capture and a refused preferred time leave the reader in two different
   * positions and are two sentences. Carried across an open and a close, because a refusal nobody has been told
   * about yet is not answered by the reader opening the form again.
   */
  readonly refusalToReport: CaptureWrite | null;
}

/** Nothing open and nothing sent, which is what the host mounts holding. */
export function noOpening(): CaptureState {
  return {
    isOpen: false,
    draft: draftFrom(),
    returnFocusTo: null,
    preferredWindow: null,
    generation: 0,
    refusedAt: null,
    refusalToReport: null,
  };
}

/**
 * The dialog opened on what a caller named, or the state untouched where it is already open.
 *
 * A DIALOG ALREADY OPEN IS LEFT ALONE. `n` pressed twice, or pressed while the form is open, must not discard what
 * the reader has typed, and the Area a caller names is the one it opens ON rather than a change to a draft in
 * flight.
 */
export function openedOn(
  held: CaptureState,
  opening: CaptureOpening,
  returnFocusTo: HTMLElement | null,
): CaptureState {
  if (held.isOpen) return held;
  return {
    isOpen: true,
    draft: draftFrom(opening),
    returnFocusTo,
    preferredWindow: opening.preferredWindow ?? null,
    generation: held.generation + 1,
    refusedAt: null,
    refusalToReport: held.refusalToReport,
  };
}

/** A closed dialog with an empty form, one opening on from whatever it closed. */
export function closedAfter(held: CaptureState): CaptureState {
  return {
    isOpen: false,
    draft: draftFrom(),
    returnFocusTo: held.returnFocusTo,
    preferredWindow: null,
    generation: held.generation + 1,
    refusedAt: null,
    refusalToReport: held.refusalToReport,
  };
}

/**
 * The opening's state once a send has answered, which turns on what landed and on whether this opening asked.
 *
 * FOUR OUTCOMES OVER TWO WRITES. A send whose opening is gone closes nothing and states nothing in a form; what it
 * can still do is name the write that failed for the top bar, because a reader who dismissed the dialog has no
 * other way to learn of it.
 */
export function stateAfter(
  current: CaptureState,
  generation: number,
  outcome: CaptureOutcome,
): CaptureState {
  const isOwn = current.generation === generation;
  if (outcome.refused === null) return isOwn ? closedAfter(current) : current;
  /* THE TASK LANDED AND ITS PREFERRED TIME DID NOT, so this opening is finished: the draft has nothing left to fix
   * and sending it again would capture the task twice. The dialog ends the way one that landed ends, and the
   * banner is what says the window is missing. */
  if (outcome.refused === "preference") {
    return { ...(isOwn ? closedAfter(current) : current), refusalToReport: "preference" };
  }
  /* NOTHING WAS CREATED, so the draft is all the reader has left: the refusal is stated in the form still holding
   * it, or in the top bar when that form has gone. */
  return isOwn ? { ...current, refusedAt: generation } : { ...current, refusalToReport: "task" };
}
