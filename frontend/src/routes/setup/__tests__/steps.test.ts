/* The four steps' four states, and the two of them that are the minimum.
 *
 * A STATUS PER STEP IS THE WHOLE SCREEN'S LOGIC, so every combination that produces a different ledger is driven
 * here rather than through the rendering: what the rows say, which one carries the caret, and which one cannot be
 * started yet.
 *
 * THE MINIMUM AGREES WITH THE API BY CONSTRUCTION. A day shape counts as declared when the WEEK PATTERN is, which is
 * what `syncr_api.plans.readiness` checks and what `POST /solve` refuses against. The case that pins it is a tenant
 * with day shapes and no pattern: the ledger must not call that step done, because the api would not. */

import { describe, expect, it } from "vitest";

import { isMinimumDeclared, missingMinimum, setupSteps, type SetupReads } from "../steps";

const NOTHING: SetupReads = {
  sourceCount: 0,
  areaCount: 0,
  dayShapeCount: 0,
  isPatternDeclared: false,
  writeTargetName: null,
};

const EVERYTHING: SetupReads = {
  sourceCount: 2,
  areaCount: 5,
  dayShapeCount: 2,
  isPatternDeclared: true,
  writeTargetName: "syncr \u00b7 plan",
};

const statusOf = (reads: SetupReads, id: string) =>
  setupSteps(reads).find((step) => step.id === id)?.status;

const noteOf = (reads: SetupReads, id: string) =>
  setupSteps(reads).find((step) => step.id === id)?.note;

describe("the ledger's four rows", () => {
  it("lists the four steps in the order the spec lists them", () => {
    expect(setupSteps(NOTHING).map((step) => step.id)).toEqual([
      "source",
      "areas",
      "day-shape",
      "bounds",
    ]);
  });

  it("marks the two minimum steps as required to solve and the other two as optional", () => {
    expect(noteOf(NOTHING, "areas")).toBe("required to solve");
    expect(noteOf({ ...NOTHING, areaCount: 1 }, "day-shape")).toBe("required to solve");
    expect(noteOf(NOTHING, "source")).toBe("optional");
    expect(noteOf(NOTHING, "bounds")).toBe("optional");
  });
});

describe("a step's four states", () => {
  it("is current on the first step that is neither done nor blocked", () => {
    expect(statusOf(NOTHING, "source")).toBe("current");
    expect(statusOf(NOTHING, "areas")).toBe("waiting");
  });

  it("moves the caret to the next unfinished step as each one is done", () => {
    const withSource = { ...NOTHING, sourceCount: 2 };
    expect(statusOf(withSource, "source")).toBe("done");
    expect(statusOf(withSource, "areas")).toBe("current");

    const withAreas = { ...withSource, areaCount: 3 };
    expect(statusOf(withAreas, "areas")).toBe("done");
    expect(statusOf(withAreas, "day-shape")).toBe("current");

    const withPattern = { ...withAreas, isPatternDeclared: true, dayShapeCount: 1 };
    expect(statusOf(withPattern, "day-shape")).toBe("done");
    expect(statusOf(withPattern, "bounds")).toBe("current");
  });

  /* Blocked and waiting are two statuses because the dependency between steps is the thing a first-run reader has
   * to see: a day shape charges its slots to Areas, so it cannot be built before one exists. */
  it("blocks the day shape while no Area exists, which is not the same as not started", () => {
    expect(statusOf(NOTHING, "day-shape")).toBe("blocked");
    expect(statusOf({ ...NOTHING, areaCount: 1 }, "day-shape")).toBe("waiting");
  });

  it("says in words what blocks it, because a dashed rule cannot say why", () => {
    expect(noteOf(NOTHING, "day-shape")).toBe("blocked until an Area exists");
  });

  it("leaves no step current once all four are done", () => {
    expect(setupSteps(EVERYTHING).some((step) => step.status === "current")).toBe(false);
    expect(setupSteps(EVERYTHING).every((step) => step.status === "done")).toBe(true);
  });

  it("passes a blocked step over when the caret is looking for the current one", () => {
    /* Areas absent blocks the day shape, so with a source already connected the caret belongs on Areas rather
       than skipping to the step that cannot be started. */
    const reads = { ...NOTHING, sourceCount: 1 };

    expect(statusOf(reads, "areas")).toBe("current");
    expect(statusOf(reads, "day-shape")).toBe("blocked");
  });
});

describe("a completed step's summary count", () => {
  it("states the count, which is what a reader checks the claim against", () => {
    expect(noteOf({ ...NOTHING, sourceCount: 2 }, "source")).toBe("2 sources");
    expect(noteOf({ ...NOTHING, areaCount: 5 }, "areas")).toBe("5 Areas");
    expect(noteOf(EVERYTHING, "day-shape")).toBe("2 day shapes");
  });

  it("is singular at one", () => {
    expect(noteOf({ ...NOTHING, sourceCount: 1 }, "source")).toBe("1 source");
    expect(noteOf({ ...NOTHING, areaCount: 1 }, "areas")).toBe("1 Area");
  });

  it("names the write target on the last step, because a count of one calendar is not a reading", () => {
    expect(noteOf(EVERYTHING, "bounds")).toBe("syncr \u00b7 plan");
  });
});

describe("the minimum a plan needs", () => {
  it("names both inputs when nothing is declared, in setup order", () => {
    expect(missingMinimum(NOTHING)).toEqual(["areas", "day-shape"]);
    expect(isMinimumDeclared(NOTHING)).toBe(false);
  });

  it("names the day shape alone once an Area exists", () => {
    expect(missingMinimum({ ...NOTHING, areaCount: 1 })).toEqual(["day-shape"]);
  });

  /* THE CASE THAT KEEPS THIS SCREEN AND THE API AGREEING. A tenant with day shapes and no week pattern has nothing
   * that materializes, so `POST /solve` refuses naming the day shape. A ledger that counted templates would call
   * the step done and leave the reader with a refusal naming an input the screen said they had. */
  it("still names the day shape while shapes exist and the pattern does not", () => {
    const shapesOnly = { ...NOTHING, areaCount: 1, dayShapeCount: 3, isPatternDeclared: false };

    expect(missingMinimum(shapesOnly)).toEqual(["day-shape"]);
    expect(statusOf(shapesOnly, "day-shape")).toBe("waiting");
  });

  it("is declared once Areas and the pattern both exist, whatever the optional steps say", () => {
    const minimum = { ...NOTHING, areaCount: 1, isPatternDeclared: true };

    expect(missingMinimum(minimum)).toEqual([]);
    expect(isMinimumDeclared(minimum)).toBe(true);
  });

  it("does not count a source or a write target towards it", () => {
    const optionalOnly = { ...NOTHING, sourceCount: 4, writeTargetName: "syncr \u00b7 plan" };

    expect(isMinimumDeclared(optionalOnly)).toBe(false);
  });
});
