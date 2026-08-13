/* THE MOVES ONE OPENING MAKES, AND THE FOUR ANSWERS A SEND CAN GET.
 *
 * DRIVEN WITHOUT A DIALOG, because that is the point of the moves being functions: a send answers after the
 * reader may have dismissed, reopened, or typed into a form, and reaching all four of those through a rendered
 * dialog costs a fixture apiece. The rendered path is driven where it belongs, over the whole gesture, in
 * `routes/backlog/__tests__/capturePreference.test.tsx`.
 *
 * THE GENERATION IS THE WHOLE MECHANISM. A send carries the number it started under; every case below is a pair
 * of a state and a number, and what is asserted is which of the two lifetimes the answer is allowed to touch. */

import { describe, expect, it } from "vitest";

import { closedAfter, noOpening, openedOn, stateAfter, type CaptureState } from "./captureState";
import type { CaptureOutcome } from "../../api/hooks/useTaskCapture";
import type { Problem } from "../../contract";

const REFUSAL: Problem = {
  type: "syncr:validation-failed",
  title: "Validation failed",
  status: 422,
  detail: "One or more members were refused.",
};

const LANDED: CaptureOutcome = { refused: null, problem: null };
const TASK_REFUSED: CaptureOutcome = { refused: "task", problem: REFUSAL };
const PREFERENCE_REFUSED: CaptureOutcome = { refused: "preference", problem: REFUSAL };

const THE_WINDOW = { from: "2026-02-11T14:00:00+00:00", to: "2026-02-11T15:00:00+00:00" };

/** An opening the reader is looking at, from an empty slot, so it carries a window. */
function opened(): CaptureState {
  return openedOn(noOpening(), { areaId: "a1", preferredWindow: THE_WINDOW }, null);
}

describe("opening", () => {
  it("carries the Area, the window, and one more generation than what it opened over", () => {
    const state = opened();

    expect(state.isOpen).toBe(true);
    expect(state.draft.areaId).toBe("a1");
    expect(state.preferredWindow).toEqual(THE_WINDOW);
    expect(state.generation).toBe(1);
  });

  /* `n` PRESSED TWICE MUST NOT DISCARD A DRAFT. The Area a caller names is the one it opens ON, so an opening
     asked for over an open dialog is not a change to the draft in flight. */
  it("leaves a dialog that is already open exactly as it was", () => {
    const held = opened();

    expect(openedOn(held, { areaId: "a2" }, null)).toBe(held);
  });
});

describe("closing", () => {
  it("empties the form, drops the window, and moves the generation on", () => {
    const closed = closedAfter(opened());

    expect(closed.isOpen).toBe(false);
    expect(closed.draft.areaId).toBe("");
    expect(closed.preferredWindow).toBeNull();
    expect(closed.generation).toBe(2);
  });

  /* A REFUSAL NOBODY HAS BEEN TOLD ABOUT SURVIVES THE CLOSE, because the reader dismissing the form is not an
     answer to it: the banner is raised from the top bar, wherever they are by then. */
  it("keeps a write still waiting to be reported", () => {
    const held: CaptureState = { ...opened(), refusalToReport: "preference" };

    expect(closedAfter(held).refusalToReport).toBe("preference");
  });
});

describe("a send whose opening is still the one on screen", () => {
  it("closes the form when both writes landed", () => {
    const held = opened();

    const after = stateAfter(held, held.generation, LANDED);

    expect(after.isOpen).toBe(false);
    expect(after.refusalToReport).toBeNull();
  });

  /* THE DRAFT IS ALL THE READER HAS LEFT when nothing was created, so the form stays up holding it and the
     refusal is marked as this opening's: no banner, because the repair is the form in front of them. */
  it("keeps the form and marks the refusal as this opening's when the task did not land", () => {
    const held = opened();

    const after = stateAfter(held, held.generation, TASK_REFUSED);

    expect(after.isOpen).toBe(true);
    expect(after.draft).toBe(held.draft);
    expect(after.refusedAt).toBe(held.generation);
    expect(after.refusalToReport).toBeNull();
  });

  /* THE TASK LANDED, so the form has nothing left to fix and sending the draft again would capture it twice: the
     opening ends the way one that landed ends, and the preferred time is named for the top bar. */
  it("closes the form and names the preference when only the preferred time did not land", () => {
    const held = opened();

    const after = stateAfter(held, held.generation, PREFERENCE_REFUSED);

    expect(after.isOpen).toBe(false);
    expect(after.refusedAt).toBeNull();
    expect(after.refusalToReport).toBe("preference");
  });
});

describe("a send whose opening has gone", () => {
  /* THE READER DISMISSED THE FORM AND THE REQUEST OUTLIVED IT. Nothing may touch the dialog they have moved on
     to, and the only thing left to do is name the write that failed for the top bar. */
  it("changes nothing when both writes landed", () => {
    const held = closedAfter(opened());

    expect(stateAfter(held, held.generation - 1, LANDED)).toBe(held);
  });

  it("names the task for the top bar when the capture was refused", () => {
    const held = closedAfter(opened());

    const after = stateAfter(held, held.generation - 1, TASK_REFUSED);

    expect(after.refusalToReport).toBe("task");
    expect(after.refusedAt).toBeNull();
    expect(after.isOpen).toBe(false);
  });

  it("names the preference for the top bar when the preferred time was refused", () => {
    const held = closedAfter(opened());

    const after = stateAfter(held, held.generation - 1, PREFERENCE_REFUSED);

    expect(after.refusalToReport).toBe("preference");
    expect(after.generation).toBe(held.generation);
  });

  /* THE READER REOPENED AND IS TYPING INTO A NEW DRAFT. A preferred time refused for the opening before it must
     not close the form they are filling in now, and it must still be reported. */
  it("leaves a form the reader has reopened open, and still names the write", () => {
    const reopened = openedOn(closedAfter(opened()), { areaId: "a3" }, null);

    const after = stateAfter(reopened, reopened.generation - 2, PREFERENCE_REFUSED);

    expect(after.isOpen).toBe(true);
    expect(after.draft.areaId).toBe("a3");
    expect(after.refusalToReport).toBe("preference");
  });
});
