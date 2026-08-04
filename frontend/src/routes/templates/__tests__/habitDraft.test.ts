/* The habit editor's patch body, and the two members that are not in it.
 *
 * A count arrives as typed text, so the cases worth pinning are the ones `Number` gets wrong: an empty box is
 * not zero, and a half-typed figure is not a body. Every bound belongs to the api, which is why a count of zero
 * is submitted here rather than refused. */

import { describe, expect, it } from "vitest";

import { habitDraftFrom, habitProposalFrom, type HabitDraft } from "../habitDraft";
import { buildFixedHabit, buildHabit } from "./fixtures";

const draftOf = (overrides: Partial<HabitDraft> = {}): HabitDraft => ({
  ...habitDraftFrom(buildHabit()),
  ...overrides,
});

const bodyOf = (draft: HabitDraft) => {
  const proposal = habitProposalFrom(draft);
  if (proposal.status !== "declarable") throw new Error(`incomplete: ${proposal.member}`);
  return proposal.body;
};

describe("the draft a habit makes", () => {
  it("carries the count its cadence uses", () => {
    expect(draftOf()).toMatchObject({
      title: "Gym",
      cadenceKind: "times_per_week",
      cadenceCount: "4",
      debtCapPeriods: "2",
    });
  });

  it("carries no count for a daily cadence, which uses neither number", () => {
    expect(habitDraftFrom(buildFixedHabit()).cadenceCount).toBe("");
  });

  it("carries the interval for an approximate cadence", () => {
    const habit = buildHabit({
      cadence: { kind: "every_approx_days", timesPerWeek: null, approxDays: 7 },
    });
    expect(habitDraftFrom(habit).cadenceCount).toBe("7");
  });

  /* Neither derivation is a member of the draft, because neither is a member of the patch shape: a control for
   * one would have nothing to send. */
  it("holds neither the cursor nor the debt figure", () => {
    expect(Object.keys(draftOf())).toEqual([
      "title",
      "cadenceKind",
      "cadenceCount",
      "minDurationMinutes",
      "maxDurationMinutes",
      "missPolicy",
      "debtCapPeriods",
    ]);
  });
});

describe("the body a draft makes", () => {
  it("sends the cadence kind and the one number that kind uses", () => {
    expect(bodyOf(draftOf()).cadence).toEqual({ kind: "times_per_week", timesPerWeek: 4 });
  });

  it("sends the interval for an approximate cadence, and not the weekly count", () => {
    const body = bodyOf(draftOf({ cadenceKind: "every_approx_days", cadenceCount: "7" }));

    expect(body.cadence).toEqual({ kind: "every_approx_days", approxDays: 7 });
  });

  /* A daily cadence takes neither number, and the api refuses the one it does not use, so a body carrying a
   * leftover count would be a stated 422. */
  it("sends neither number for a daily cadence, even with a count in the box", () => {
    const body = bodyOf(draftOf({ cadenceKind: "daily", cadenceCount: "4" }));

    expect(body.cadence).toEqual({ kind: "daily" });
  });

  it("trims the title, so a name of spaces is not stored as one", () => {
    expect(bodyOf(draftOf({ title: "  Gym  " })).title).toBe("Gym");
  });

  it("carries no member for the cursor or the debt figure", () => {
    const body = bodyOf(draftOf());

    expect(body).not.toHaveProperty("cursor");
    expect(body).not.toHaveProperty("debt");
    expect(body).not.toHaveProperty("areaId");
  });

  /* Every bound is the api's: a count of zero is refused there, naming the member, and a second copy of the
   * bound in the browser would be a second thing to keep true. */
  it.each([
    ["zero", "0", 0],
    ["past the weekly maximum", "200", 200],
  ])("submits a count %s rather than refusing it here", (_, typed, expected) => {
    expect(bodyOf(draftOf({ cadenceCount: typed })).cadence).toEqual({
      kind: "times_per_week",
      timesPerWeek: expected,
    });
  });
});

describe("a draft that is not a body", () => {
  it.each([
    ["an empty box", ""],
    ["only spaces", "   "],
    ["a fraction", "4.5"],
    ["a word", "four"],
    ["a negative", "-4"],
  ])("refuses %s as a cadence count, naming the member", (_, typed) => {
    const proposal = habitProposalFrom(draftOf({ cadenceCount: typed }));

    expect(proposal.status).toBe("incomplete");
    if (proposal.status !== "incomplete") throw new Error("the draft was declarable");
    expect(proposal.member).toBe("cadenceCount");
  });

  it("refuses a blank title", () => {
    const proposal = habitProposalFrom(draftOf({ title: "   " }));

    expect(proposal.status).toBe("incomplete");
    if (proposal.status !== "incomplete") throw new Error("the draft was declarable");
    expect(proposal.member).toBe("title");
  });

  it("refuses a debt cap that is not a whole number", () => {
    const proposal = habitProposalFrom(draftOf({ debtCapPeriods: "" }));

    expect(proposal.status).toBe("incomplete");
    if (proposal.status !== "incomplete") throw new Error("the draft was declarable");
    expect(proposal.member).toBe("debtCapPeriods");
  });

  /* A daily habit's count box is not sent, so refusing on it would leave a reader unable to save until they
   * cleared a value the request never carries. */
  it("declares a daily habit whose count box holds nonsense", () => {
    expect(habitProposalFrom(draftOf({ cadenceKind: "daily", cadenceCount: "x" })).status).toBe(
      "declarable",
    );
  });
});
