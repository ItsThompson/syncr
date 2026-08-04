/* The anchor-type editor's patch body, the reordering, and the refusal a rejected edit renders.
 *
 * The line these pin is which refusals belong here: the recovery scope's own membership, and nothing else. The
 * prep-lead collision is the api's and its 422 is what the screen renders, so a draft that will be refused is
 * still declarable here. That is deliberate, and the last case in this file is the proof that the refusal
 * survives to the reader with the member named. */

import { describe, expect, it } from "vitest";

import {
  anchorTypeDraftFrom,
  anchorTypeProposalFrom,
  type AnchorTypeDraft,
} from "../anchorTypeDraft";
import { movedEarlier, movedLater } from "../order";
import { messageFor, rejectionNotice } from "../rejection";
import {
  AREA_CAREER,
  AREA_FITNESS,
  buildAnchorType,
  buildLectureType,
  buildPrepCollision,
} from "./fixtures";

const draftOf = (overrides: Partial<AnchorTypeDraft> = {}): AnchorTypeDraft => ({
  ...anchorTypeDraftFrom(buildAnchorType()),
  ...overrides,
});

const bodyOf = (draft: AnchorTypeDraft) => {
  const proposal = anchorTypeProposalFrom(draft);
  if (proposal.status !== "declarable") throw new Error(`incomplete: ${proposal.member}`);
  return proposal.body;
};

describe("the draft a type makes", () => {
  it("carries every geometry member the editor exposes", () => {
    expect(draftOf()).toEqual({
      prepLeadMinutes: 360,
      prepDurationMinutes: 30,
      prepAreaId: AREA_CAREER,
      transitLeadMinutes: 30,
      transitDurationMinutes: 30,
      returnTransitMinutes: 30,
      transitAreaId: AREA_CAREER,
      postBufferMinutes: 75,
      postScope: "areas",
      forbiddenAreaIds: [AREA_CAREER],
    });
  });

  /* Null is the abutting default, meaning leave exactly late enough to arrive on time. Reading it as zero would
   * place the outbound leg AT the commitment. */
  it("keeps a null transit lead as null rather than as zero", () => {
    expect(draftOf({ ...anchorTypeDraftFrom(buildLectureType()) }).transitLeadMinutes).toBeNull();
  });

  it("carries neither the name nor the match rules, which this editor does not change", () => {
    expect(draftOf()).not.toHaveProperty("name");
    expect(draftOf()).not.toHaveProperty("matchTitleContains");
  });
});

describe("the body a draft makes", () => {
  it("sends every geometry member, because each is an absolute value", () => {
    expect(bodyOf(draftOf())).toEqual({
      prepLeadMinutes: 360,
      prepDurationMinutes: 30,
      prepAreaId: AREA_CAREER,
      transitLeadMinutes: 30,
      transitDurationMinutes: 30,
      returnTransitMinutes: 30,
      transitAreaId: AREA_CAREER,
      postBufferMinutes: 75,
      postScope: "areas",
      forbiddenAreaIds: [AREA_CAREER],
    });
  });

  it("carries an explicit null to clear a prep Area, which makes prep a forbidden window", () => {
    expect(bodyOf(draftOf({ prepAreaId: null })).prepAreaId).toBeNull();
  });

  it("carries an explicit null to restore the abutting transit lead", () => {
    expect(bodyOf(draftOf({ transitLeadMinutes: null })).transitLeadMinutes).toBeNull();
  });

  /* The list carries the members of the one scope that has members, and the api holds the two to each other, so
   * a scope change has to clear the list rather than leave it to be ignored. */
  it.each(["none", "all"] as const)("empties the forbidden Areas when the scope is %s", (scope) => {
    expect(bodyOf(draftOf({ postScope: scope })).forbiddenAreaIds).toEqual([]);
  });

  it("keeps every named Area when the scope names Areas", () => {
    const body = bodyOf(draftOf({ forbiddenAreaIds: [AREA_CAREER, AREA_FITNESS] }));

    expect(body.forbiddenAreaIds).toEqual([AREA_CAREER, AREA_FITNESS]);
  });

  it("refuses a scope naming Areas with none named, and says which control to use", () => {
    const proposal = anchorTypeProposalFrom(draftOf({ forbiddenAreaIds: [] }));

    expect(proposal.status).toBe("incomplete");
    if (proposal.status !== "incomplete") throw new Error("the draft was declarable");
    expect(proposal.member).toBe("forbiddenAreas");
    expect(proposal.reason).toContain("forbid nothing");
  });

  /* THE COLLISION IS NOT CHECKED HERE. A prep lead under its own prep duration plus the transit lead is refused
   * by the api naming the member, and a second copy of that arithmetic in the browser could drift from the
   * constraint the table holds. */
  it("declares a prep lead the api will refuse, because that refusal is the api's to state", () => {
    const proposal = anchorTypeProposalFrom(
      draftOf({ prepLeadMinutes: 15, prepDurationMinutes: 30, transitLeadMinutes: 30 }),
    );

    expect(proposal.status).toBe("declarable");
  });
});

describe("moving a rule through the evaluation order", () => {
  const order = ["a", "b", "c"];

  it("moves one place earlier", () => {
    expect(movedEarlier(order, "c")).toEqual(["a", "c", "b"]);
  });

  it("moves one place later", () => {
    expect(movedLater(order, "a")).toEqual(["b", "a", "c"]);
  });

  it("answers the whole order, so a partial one cannot be sent", () => {
    expect(movedLater(order, "a")).toHaveLength(order.length);
    expect([...movedLater(order, "a")].toSorted()).toEqual([...order].toSorted());
  });

  /* The same array, not an equal one: the caller sends nothing when the order did not change, and a reorder
   * that reorders nothing still re-evaluates every commitment. */
  it.each([
    ["the first rule earlier", movedEarlier, "a"],
    ["the last rule later", movedLater, "c"],
    ["a rule the order does not hold", movedEarlier, "z"],
  ])("leaves the order untouched when moving %s", (_, move, id) => {
    expect(move(order, id)).toBe(order);
  });

  it("does not mutate the order it was given", () => {
    movedLater(order, "a");
    expect(order).toEqual(["a", "b", "c"]);
  });
});

describe("a refused edit", () => {
  const problem = buildPrepCollision();

  it("is amber and inline, because nothing is broken and the repair is the form", () => {
    const notice = rejectionNotice({ id: "x", problem, stillWorks: "every other anchor type" });

    expect(notice.pigment).toBe("amber");
    expect(notice.volume).toBe("inline");
  });

  it("names the member to change, in the api's own words", () => {
    const notice = rejectionNotice({ id: "x", problem, stillWorks: "every other anchor type" });

    expect(notice.detail).toContain("prepLeadMinutes must be at least 60");
    expect(notice.detail).toContain(problem.detail);
  });

  it("names what still works, which the notice type refuses to let a caller omit", () => {
    const notice = rejectionNotice({ id: "x", problem, stillWorks: "every other anchor type" });

    expect(notice.stillWorks).toEqual(["every other anchor type"]);
    expect(notice.unavailable).toEqual([]);
  });

  it("carries the api's sentence alone when the refusal names no member", () => {
    const conflict = { ...problem, errors: null };
    const notice = rejectionNotice({ id: "x", problem: conflict, stillWorks: "the rules" });

    expect(notice.detail).toBe(conflict.detail);
  });

  it("hands each member's message to the row that owns it, and to no other", () => {
    expect(messageFor(problem, "prepLeadMinutes")).toContain("must be at least 60");
    expect(messageFor(problem, "transitLeadMinutes")).toBeUndefined();
    expect(messageFor(null, "prepLeadMinutes")).toBeUndefined();
  });
});
