/* Whether a routine is one the solver may propose shortening.
 *
 * THE PREDICATE IS THE WHOLE OF IT. Nothing marks a routine as special, so what these cases pin is that the answer
 * comes from the two durations and from nothing else: the same title with two different floors answers differently,
 * and two different titles with the same floor answer the same. */

import { describe, expect, it } from "vitest";

import { isElastic } from "../routineFloor";
import { buildLunch, buildRoutine } from "./fixtures";

describe("whether a routine is negotiable", () => {
  /* A floor equal to the target is the default for every routine and is what makes one incompressible. The
   * `reduce_routine` tradeoff is offered only where the floor is below the target. */
  it("is not, while the floor equals the target", () => {
    expect(isElastic(buildRoutine())).toBe(false);
    expect(isElastic(buildLunch())).toBe(false);
  });

  it("is, once the floor is below the target", () => {
    expect(isElastic(buildRoutine({ minDurationMinutes: 390 }))).toBe(true);
    expect(isElastic(buildLunch({ minDurationMinutes: 30 }))).toBe(true);
  });

  it("answers from the durations rather than from the title", () => {
    expect(isElastic(buildRoutine({ title: "Kip", minDurationMinutes: 390 }))).toBe(true);
    expect(isElastic(buildRoutine({ title: "Sleep" }))).toBe(false);
  });

  /* One minute of give is give, and the api accepts it: the bound is `0 <`, not a band. */
  it("is, one minute below the target", () => {
    expect(isElastic(buildRoutine({ minDurationMinutes: 479 }))).toBe(true);
  });
});
