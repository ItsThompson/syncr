/* THE WORDS A REFUSED WRITE REACHES A READER IN, AND THE VOLUME AND PIGMENT THEY ARRIVE AT.
 *
 * The severity assignment is asserted through the factory the shell calls rather than against a table restating a
 * table, which is the same instrument `routes/__tests__/noticeVolumes.test.ts` uses over every notice in the tree.
 * What is local to this file is the sentence: a reader who has left the form needs three facts, and the notice is
 * only as good as whether it carries all three. */

import { describe, expect, it } from "vitest";

import { captureNotSavedNotice } from "./refusedWrites";
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
