/* The coercion at the boundary. Not every non-2xx body is a problem document, and a component
 * renders `problem.detail`, so the boundary owes it a real one. */

import { describe, expect, it } from "vitest";

import {
  UNEXPECTED_PROBLEM_TYPE,
  UNREACHABLE_PROBLEM_TYPE,
  toProblem,
  unreachableProblem,
  type Problem,
} from "./problem";

const contractProblem: Problem = {
  type: "syncr:validation-failed",
  title: "Validation failed",
  status: 422,
  detail: "A minimum chunk cannot exceed its estimate.",
};

describe("toProblem", () => {
  it("passes the api's own problem document through unchanged", () => {
    expect(toProblem(contractProblem, new Response(null, { status: 422 }))).toBe(contractProblem);
  });

  it("keeps the optional members the contract declares", () => {
    const withErrors: Problem = {
      ...contractProblem,
      instance: "01H8",
      errors: [{ field: "minimumChunkMinutes", message: "above the estimate" }],
    };
    expect(toProblem(withErrors, new Response(null, { status: 422 }))).toEqual(withErrors);
  });

  it.each([
    ["an html error page", "<html>bad gateway</html>"],
    ["an empty body", null],
    ["a partial document", { title: "Oops" }],
    ["a document with the wrong status type", { ...contractProblem, status: "422" }],
  ])("synthesises one from %s", (_, body) => {
    const problem = toProblem(body, new Response(null, { status: 502 }));

    expect(problem.type).toBe(UNEXPECTED_PROBLEM_TYPE);
    expect(problem.status).toBe(502);
  });

  it("names the capabilities that survive, not only what broke", () => {
    const problem = toProblem(null, new Response(null, { status: 502 }));
    expect(problem.detail).toContain("the rest of the app is unaffected");
  });
});

describe("unreachableProblem", () => {
  it("carries the cause's message, so a reader can tell a refusal from a timeout", () => {
    const problem = unreachableProblem(new TypeError("Failed to fetch"));

    expect(problem.type).toBe(UNREACHABLE_PROBLEM_TYPE);
    expect(problem.detail).toContain("Failed to fetch");
  });

  it("states that nothing was sent, because that is what a reader needs to know", () => {
    expect(unreachableProblem("unknown").detail).toContain("Nothing was sent");
  });

  it("uses a status no HTTP response can carry, so it cannot be mistaken for one", () => {
    expect(unreachableProblem(new Error("boom")).status).toBe(0);
  });
});
