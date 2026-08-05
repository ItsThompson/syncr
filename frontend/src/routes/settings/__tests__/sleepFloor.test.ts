/* Finding the sleep routine, and whether it is negotiable.
 *
 * NOTHING ON A ROUTINE MARKS ONE AS SLEEP, so the title is what identifies it. That is a real coupling and these
 * cases pin it: the match is trimmed and case-insensitive, two routines may share a title so the first wins, and a
 * tenant with no such routine has no floor to set rather than a control with nothing behind it. */

import { describe, expect, it } from "vitest";

import { isElastic, sleepRoutineOf } from "../sleepFloor";
import { ROUTINE_SLEEP, buildLunch, buildRoutine } from "./fixtures";

describe("finding the sleep routine", () => {
  it("finds it by title", () => {
    expect(sleepRoutineOf([buildLunch(), buildRoutine()])?.id).toBe(ROUTINE_SLEEP);
  });

  it("finds it whatever case and spacing the title carries", () => {
    expect(sleepRoutineOf([buildRoutine({ title: "  SLEEP " })])?.id).toBe(ROUTINE_SLEEP);
  });

  /* Two routines may legitimately share a title, so the first is the one, which is the order the list is read in. */
  it("takes the first where two share the title", () => {
    const second = buildRoutine({ id: "8a1d5f20-0009-4b7e-9c31-0000000000r9", title: "Sleep" });

    expect(sleepRoutineOf([buildRoutine(), second])?.id).toBe(ROUTINE_SLEEP);
  });

  it("answers null where no routine is titled Sleep, rather than guessing at the longest one", () => {
    expect(sleepRoutineOf([buildLunch()])).toBeNull();
    expect(sleepRoutineOf([])).toBeNull();
  });

  it("does not match a title that merely contains the word", () => {
    expect(sleepRoutineOf([buildRoutine({ title: "Sleep in on Sunday" })])).toBeNull();
  });
});

describe("whether sleep is negotiable", () => {
  /* A floor equal to the target is the default for every routine and is what makes one incompressible. The
   * `reduce_routine` tradeoff is offered only where the floor is below the target. */
  it("is not, while the floor equals the target", () => {
    expect(isElastic(buildRoutine())).toBe(false);
  });

  it("is, once the floor is below the target", () => {
    expect(isElastic(buildRoutine({ minDurationMinutes: 390 }))).toBe(true);
  });
});
