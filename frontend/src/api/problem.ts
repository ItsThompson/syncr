/* RFC 9457 problem details, as the generated schema declares them, plus the one coercion
 * that turns an arbitrary failure into that shape.
 *
 * The coercion exists because not every non-2xx body is a problem document. A readiness 503
 * carries the readiness payload; a proxy or a tunnel can answer with HTML; a dropped
 * connection produces no body at all. A component renders `problem.detail`, so the boundary
 * owes it a real Problem rather than an `unknown` cast. */

import type { components } from "./schema";

export type Problem = components["schemas"]["Problem"];

const isProblem = (value: unknown): value is Problem => {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.type === "string" &&
    typeof candidate.title === "string" &&
    typeof candidate.detail === "string" &&
    typeof candidate.status === "number"
  );
};

/** The problem type used when the failure did not come from the api's error contract. */
export const UNEXPECTED_PROBLEM_TYPE = "syncr:unexpected-response";

/** The problem type used when the request never reached the api. */
export const UNREACHABLE_PROBLEM_TYPE = "syncr:api-unreachable";

export function toProblem(body: unknown, response: Response): Problem {
  if (isProblem(body)) return body;
  return {
    type: UNEXPECTED_PROBLEM_TYPE,
    title: "Unexpected response",
    status: response.status,
    detail:
      `The api answered ${response.status} without a problem document. ` +
      "Reading and writing are both unavailable on this path; the rest of the app is unaffected.",
  };
}

export function unreachableProblem(cause: unknown): Problem {
  return {
    type: UNREACHABLE_PROBLEM_TYPE,
    title: "The api could not be reached",
    status: 0,
    detail:
      cause instanceof Error
        ? `The request did not complete: ${cause.message}. Nothing was sent, so nothing changed.`
        : "The request did not complete. Nothing was sent, so nothing changed.",
  };
}
