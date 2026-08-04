/* The entry editor's two request bodies, and the refusal that is a control shape rather than a message.
 *
 * The pairing rule is what these assert: a concrete body carries a binding and no Area, a slot body carries an
 * Area and has nowhere to put a binding, and a draft missing its kind's own member is not a body at all. */

import { describe, expect, it } from "vitest";

import { bindingFrom, bindingValue } from "../bindings";
import { EMPTY_ENTRY_DRAFT, entryProposalFrom, type EntryDraft } from "../entryDraft";
import { AREA_CAREER, HABIT_GYM, ROUTINE_WAKE } from "./fixtures";

const concrete = (overrides: Partial<EntryDraft> = {}): EntryDraft => ({
  ...EMPTY_ENTRY_DRAFT,
  binding: { target: "routine", ref: ROUTINE_WAKE },
  ...overrides,
});

describe("a binding's select value", () => {
  it("carries the table as well as the identifier, which the identifier alone does not say", () => {
    expect(bindingValue({ target: "habit", ref: HABIT_GYM })).toBe(`habit:${HABIT_GYM}`);
  });

  it("round-trips", () => {
    const choice = { target: "routine", ref: ROUTINE_WAKE } as const;
    expect(bindingFrom(bindingValue(choice))).toEqual(choice);
  });

  /* An identifier without a table is what probing both tables would have to guess at, and two rows sharing an
   * identifier would resolve to whichever was probed first. */
  it.each([
    ["a value with no table", ROUTINE_WAKE],
    ["a table nothing answers for", `project:${ROUTINE_WAKE}`],
    ["a table with no identifier", "habit:"],
    ["nothing at all", ""],
  ])("answers null for %s rather than guessing", (_, value) => {
    expect(bindingFrom(value)).toBeNull();
  });

  it("keeps an identifier that contains the separator", () => {
    expect(bindingFrom("habit:a:b")).toEqual({ target: "habit", ref: "a:b" });
  });
});

describe("a concrete entry", () => {
  it("declares the binding it names, and no Area", () => {
    const proposal = entryProposalFrom(
      concrete({ targetTime: "05:00", durationMinutes: 15, flexBandMinutes: 30 }),
    );

    expect(proposal).toEqual({
      status: "declarable",
      body: {
        kind: "concrete",
        targetTime: "05:00",
        durationMinutes: 15,
        flexBandMinutes: 30,
        bindingTarget: "routine",
        bindingRef: ROUTINE_WAKE,
      },
    });
  });

  it("cannot be declared with no binding, and names the member to choose", () => {
    const proposal = entryProposalFrom({ ...EMPTY_ENTRY_DRAFT, binding: null });

    expect(proposal.status).toBe("incomplete");
    if (proposal.status !== "incomplete") throw new Error("the draft was declarable");
    expect(proposal.member).toBe("binding");
    expect(proposal.reason).toContain("names the routine or habit");
  });

  /* An Area on a concrete entry is a statement about reporting, and the boundary accepts one. The form does not
   * offer it, so a draft carrying one still declares the entry's content rather than an Area-only body. */
  it("does not carry an Area even when the draft holds one", () => {
    const proposal = entryProposalFrom(concrete({ areaId: AREA_CAREER }));

    expect(proposal.status).toBe("declarable");
    if (proposal.status !== "declarable") throw new Error("the draft was not declarable");
    expect(proposal.body).not.toHaveProperty("areaId");
  });
});

describe("a slot", () => {
  it("declares the Area it reserves time for, and no binding", () => {
    const proposal = entryProposalFrom({
      ...EMPTY_ENTRY_DRAFT,
      kind: "slot",
      areaId: AREA_CAREER,
      targetTime: "07:00",
      durationMinutes: 150,
      flexBandMinutes: 30,
    });

    expect(proposal).toEqual({
      status: "declarable",
      body: {
        kind: "slot",
        targetTime: "07:00",
        durationMinutes: 150,
        flexBandMinutes: 30,
        areaId: AREA_CAREER,
      },
    });
  });

  it("cannot be declared with no Area, and names the member to choose", () => {
    const proposal = entryProposalFrom({ ...EMPTY_ENTRY_DRAFT, kind: "slot", areaId: null });

    expect(proposal.status).toBe("incomplete");
    if (proposal.status !== "incomplete") throw new Error("the draft was declarable");
    expect(proposal.member).toBe("area");
    expect(proposal.reason).toContain("one Area");
  });

  /* A slot has nowhere to put a binding: the api rejects an unknown member, so a body carrying one would be a
   * stated 422 rather than a value quietly dropped. */
  it("carries no binding even when the draft holds one", () => {
    const proposal = entryProposalFrom(concrete({ kind: "slot", areaId: AREA_CAREER }));

    expect(proposal.status).toBe("declarable");
    if (proposal.status !== "declarable") throw new Error("the draft was not declarable");
    expect(proposal.body).not.toHaveProperty("bindingRef");
    expect(proposal.body).not.toHaveProperty("bindingTarget");
  });
});

describe("the empty draft", () => {
  it("starts on the kind that needs a choice, so nothing is declared by default", () => {
    expect(EMPTY_ENTRY_DRAFT.kind).toBe("concrete");
    expect(entryProposalFrom(EMPTY_ENTRY_DRAFT).status).toBe("incomplete");
  });

  it("declares no flex band, which is the api's own default", () => {
    expect(EMPTY_ENTRY_DRAFT.flexBandMinutes).toBe(0);
  });
});
