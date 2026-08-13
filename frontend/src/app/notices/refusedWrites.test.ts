/* THE WORDS A REFUSED WRITE REACHES A READER IN, AND THE VOLUME AND PIGMENT THEY ARRIVE AT.
 *
 * The severity assignment is asserted through the factory the shell calls rather than against a table restating a
 * table, which is the same instrument `routes/__tests__/noticeVolumes.test.ts` uses over every notice in the tree.
 * What is local to this file is the sentence: a reader who has left the form needs three facts, and the notice is
 * only as good as whether it carries all three.
 *
 * A CAPTURE IS TWO WRITES AND THE TWO SENTENCES ARE NOT INTERCHANGEABLE. One says the task is gone and the title
 * went with it; the other says the task is in the list and only its preferred time is missing. Reading a task that
 * WAS saved as one that was not would send a reader to type it again, so each is asserted on the fact it turns on,
 * and the mapping from the refused write to the sentence is asserted rather than left to a call site. */

import { describe, expect, it } from "vitest";

import {
  captureNotSavedNotice,
  notSavedNotice,
  preferredTimeNotSavedNotice,
} from "./refusedWrites";
import type { Problem } from "../../contract";

const REFUSED: Problem = {
  type: "syncr:validation-failed",
  title: "That task was not accepted",
  status: 422,
  detail: "The estimate has to be at least as long as the minimum chunk.",
};

describe("a capture the api refused after its form had gone", () => {
  it("takes the top bar in oxide, because a durable write did not happen", () => {
    const notice = captureNotSavedNotice(REFUSED);

    expect(notice.volume).toBe("banner");
    expect(notice.pigment).toBe("oxide");
  });

  it("names what still works: the backlog is unchanged and the capture can be made again", () => {
    expect(captureNotSavedNotice(REFUSED).stillWorks).toEqual([
      "your backlog, which is unchanged",
      "capturing the task again",
    ]);
  });

  /* THE TITLE IS THE ONE THING THE READER LOSES THAT SYNCR COULD HAVE HELD. Saying so is what stops them looking
   * for a form the product is keeping for them, which is why it is in the sentence rather than left to be
   * inferred from a task that is not in the backlog. */
  it("says the api's own reason and that the typed title went with the form", () => {
    const notice = captureNotSavedNotice(REFUSED);

    expect(notice.detail).toContain(REFUSED.detail);
    expect(notice.detail).toContain("The title you typed was not saved");
  });

  it("offers no repair, because there is nothing to repair: the resolution is knowing", () => {
    expect(captureNotSavedNotice(REFUSED).action).toBeNull();
  });

  /* NOTHING IS UNAVAILABLE. Capture works, the backlog reads as it did, and one task was refused: a capability
   * named here would tell a reader something is down when nothing is. */
  it("names no lost capability", () => {
    expect(captureNotSavedNotice(REFUSED).unavailable).toEqual([]);
  });
});

describe("a task that landed whose own preferred time the api refused", () => {
  it("takes the top bar in oxide, because a durable write did not happen", () => {
    const notice = preferredTimeNotSavedNotice(REFUSED);

    expect(notice.volume).toBe("banner");
    expect(notice.pigment).toBe("oxide");
  });

  /* THE READER'S FIRST QUESTION IS WHETHER THEY HAVE TO TYPE IT AGAIN, and the answer is no: the task was created
   * and only the window is missing. Saying that first is what stops them capturing it a second time. */
  it("says the task itself was saved, and that nothing typed was lost", () => {
    const notice = preferredTimeNotSavedNotice(REFUSED);

    expect(notice.detail).toContain("The task itself was saved.");
    expect(notice.detail).toContain("Nothing you typed was lost");
    expect(notice.detail).toContain(REFUSED.detail);
  });

  it("names what still works: the task is in the backlog and the next plan will place it", () => {
    expect(preferredTimeNotSavedNotice(REFUSED).stillWorks).toEqual([
      "the task, which is in your backlog",
      "the next plan, which will place it without a preferred time",
    ]);
  });

  /* THE CAPTURE'S OWN SENTENCE WOULD BE FALSE HERE, on both of its claims: the backlog is not unchanged and the
   * title was not lost. A shared id would also mean one banner replacing the other, so a reader who met both
   * conditions would be told about one. */
  it("says neither of the things the refused capture says, and stands under its own id", () => {
    const notice = preferredTimeNotSavedNotice(REFUSED);

    expect(notice.detail).not.toContain("was not saved either");
    expect(notice.stillWorks).not.toContain("your backlog, which is unchanged");
    expect(notice.id).not.toBe(captureNotSavedNotice(REFUSED).id);
  });

  it("offers no repair, because no surface in this product authors a task's own preferred time", () => {
    expect(preferredTimeNotSavedNotice(REFUSED).action).toBeNull();
  });

  /* THE TASK IS THERE AND THE PLAN STILL RUNS. A capability named here would report a system that is down over one
   * window nobody stored. */
  it("names no lost capability", () => {
    expect(preferredTimeNotSavedNotice(REFUSED).unavailable).toEqual([]);
  });
});

describe("which sentence a refused write gets", () => {
  /* THE MAPPING IS THE THING A CALL SITE CANNOT GET WRONG TWICE. Both conditions arrive at one call, so if it
   * answered the same notice for both, every case above would still pass and every reader would be told the wrong
   * one. */
  it("is the capture's for a refused task and the preferred time's for a refused preference", () => {
    expect(notSavedNotice("task", REFUSED)).toEqual(captureNotSavedNotice(REFUSED));
    expect(notSavedNotice("preference", REFUSED)).toEqual(preferredTimeNotSavedNotice(REFUSED));
  });
});
