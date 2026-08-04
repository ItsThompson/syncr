/* Turning an identifier into a name, and the span the commitments are read over.
 *
 * The case that matters is the missing row: the api does not check that a concrete entry's binding names a
 * routine or habit that exists, so an entry naming a removed routine is reachable and must not render as an
 * identifier or as an empty cell. */

import { describe, expect, it } from "vitest";

import { areaOf, bindingNameOf } from "../naming";
import { fortnightFrom } from "../span";
import {
  AREA_CAREER,
  HABIT_GYM,
  ROUTINE_WAKE,
  buildAreas,
  buildEntry,
  buildHabit,
  buildRoutine,
} from "./fixtures";

const areas = buildAreas().areas;
const routines = [buildRoutine()];
const habits = [buildHabit()];

describe("areaOf", () => {
  it("finds the Area an identifier names", () => {
    expect(areaOf(areas, AREA_CAREER)?.name).toBe("Career");
  });

  it("answers null for no identifier, which is a frame entry", () => {
    expect(areaOf(areas, null)).toBeNull();
  });

  it("answers null for an identifier this tenant holds no Area for", () => {
    expect(areaOf(areas, "3f1b7a3c-9999-4c8e-9a11-00000000ffff")).toBeNull();
  });
});

describe("bindingNameOf", () => {
  it("names the routine a concrete entry binds", () => {
    expect(bindingNameOf(buildEntry(), routines, habits)).toBe("Wake Up");
  });

  it("names the habit a concrete entry binds", () => {
    const entry = buildEntry({ bindingTarget: "habit", bindingRef: HABIT_GYM });

    expect(bindingNameOf(entry, routines, habits)).toBe("Gym");
  });

  /* The identifier alone does not say which table to read, and two rows sharing one would resolve to whichever
   * was probed first. The discriminator is what this asserts: the same identifier under the other target finds
   * nothing rather than the routine of that name. */
  it("reads the table the entry names and not the other one", () => {
    const entry = buildEntry({ bindingTarget: "habit", bindingRef: ROUTINE_WAKE });

    expect(bindingNameOf(entry, routines, habits)).toBeNull();
  });

  it("answers null for a slot, which names no content at all", () => {
    const slot = buildEntry({ kind: "slot", bindingTarget: null, bindingRef: null });

    expect(bindingNameOf(slot, routines, habits)).toBeNull();
  });

  it("answers null for a binding whose row is gone, so the cell can say so", () => {
    const entry = buildEntry({ bindingRef: "3f1b7a3c-9999-4c8e-9a11-00000000eeee" });

    expect(bindingNameOf(entry, routines, habits)).toBeNull();
  });

  /* The pairing rule is the api's, and a response that broke it would still have to render: an identifier with
   * no table says which row to read in neither of them. */
  it("answers null for a binding that names no table", () => {
    const entry = buildEntry({ bindingTarget: null, bindingRef: ROUTINE_WAKE });

    expect(bindingNameOf(entry, routines, habits)).toBeNull();
  });
});

describe("fortnightFrom", () => {
  it("spans fourteen days from the instant it is given", () => {
    const span = fortnightFrom(new Date("2026-08-04T09:00:00Z"));

    expect(span).toEqual({ from: "2026-08-04T09:00:00.000Z", to: "2026-08-18T09:00:00.000Z" });
  });

  /* The api refuses an instant carrying no offset, answering 422 rather than 500, so both bounds have to state
   * one. `Z` is that offset. */
  it("states an offset on both bounds", () => {
    const span = fortnightFrom(new Date("2026-08-04T09:00:00Z"));

    expect(span.from.endsWith("Z")).toBe(true);
    expect(span.to.endsWith("Z")).toBe(true);
  });

  /* Fourteen nominal days, counted in elapsed time, so a span crossing a daylight-saving transition is still
   * fourteen days of commitments rather than thirteen and twenty-three hours of them. */
  it("spans the same elapsed time across a daylight-saving transition", () => {
    const span = fortnightFrom(new Date("2026-03-22T12:00:00Z"));

    expect(span.to).toBe("2026-04-05T12:00:00.000Z");
  });
});
