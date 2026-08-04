/* Several reads as one reading.
 *
 * Two claims are worth pinning: the data comes back under the names it went in under, and a refusal outranks an
 * outstanding read, so a surface says what broke rather than waiting for something that will not arrive. */

import { describe, expect, it } from "vitest";

import { readingOf } from "./reading";
import type { Problem } from "../contract";

const problem: Problem = {
  type: "syncr:unexpected-response",
  title: "Unexpected response",
  status: 502,
  detail: "The api answered 502 without a problem document.",
};

const other: Problem = { ...problem, status: 503, detail: "The api answered 503." };

describe("readingOf", () => {
  it("is ready with every value under the name it was given", () => {
    const reading = readingOf({
      shapes: { status: "ready", data: [1, 2] } as const,
      name: { status: "ready", data: "Weekday" } as const,
    });

    expect(reading).toEqual({ status: "ready", data: { shapes: [1, 2], name: "Weekday" } });
  });

  it("is ready for a falsy value, which is data rather than absence", () => {
    const reading = readingOf({ count: { status: "ready", data: 0 } as const });

    expect(reading).toEqual({ status: "ready", data: { count: 0 } });
  });

  it("is ready for a null value, which the week pattern uses for `not declared yet`", () => {
    const reading = readingOf({ pattern: { status: "ready", data: null } as const });

    expect(reading).toEqual({ status: "ready", data: { pattern: null } });
  });

  it("is loading while any read is outstanding", () => {
    const reading = readingOf({
      shapes: { status: "ready", data: [1] } as const,
      areas: { status: "loading" } as const,
    });

    expect(reading).toEqual({ status: "loading" });
  });

  it("names the read that failed, so the surface can say which one", () => {
    const reading = readingOf({
      shapes: { status: "ready", data: [1] } as const,
      areas: { status: "error", problem } as const,
    });

    expect(reading).toEqual({ status: "error", problem, name: "areas" });
  });

  /* A refusal outranks an outstanding read whichever order they arrive in: the surface cannot be drawn either
   * way, and a reader waiting for a screen that will not appear learns nothing. */
  it.each([
    [
      "the failure first",
      { areas: { status: "error", problem } as const, shapes: { status: "loading" } as const },
    ],
    [
      "the failure last",
      { shapes: { status: "loading" } as const, areas: { status: "error", problem } as const },
    ],
  ])("reports the failure over the outstanding read, with %s", (_, resources) => {
    const reading = readingOf(resources);

    expect(reading.status).toBe("error");
    if (reading.status !== "error") throw new Error("the reading was not an error");
    expect(reading.name).toBe("areas");
  });

  it("reports the first failure when two reads failed", () => {
    const reading = readingOf({
      shapes: { status: "error", problem } as const,
      areas: { status: "error", problem: other } as const,
    });

    expect(reading).toEqual({ status: "error", problem, name: "shapes" });
  });

  it("is ready with nothing when it is given nothing", () => {
    expect(readingOf({})).toEqual({ status: "ready", data: {} });
  });
});
