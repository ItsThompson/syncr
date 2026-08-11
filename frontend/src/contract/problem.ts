/* RFC 9457 problem details, as the generated schema declares them, widened by the ones the client
 * mints, plus the one coercion that turns an arbitrary failure into that shape.
 *
 * The coercion exists because not every non-2xx body is a problem document. A readiness 503
 * carries the readiness payload; a proxy or a tunnel can answer with HTML; a dropped
 * connection produces no body at all. A component renders `problem.detail`, so the boundary
 * owes it a real Problem rather than an `unknown` cast. */

import type { components } from "../api/schema";

/** A problem document as the api's contract declares it, `type` included: the document publishes
 * the api's error vocabulary as an enum, so this is where the union comes from. */
type ApiProblem = components["schemas"]["Problem"];

/** The problem type used when the failure did not come from the api's error contract. */
export const UNEXPECTED_PROBLEM_TYPE = "syncr:unexpected-response";

/** The problem type used when the request never reached the api. */
export const UNREACHABLE_PROBLEM_TYPE = "syncr:api-unreachable";

/** The problem type used when a write had no row to send it for, so nothing was sent. */
export const NOTHING_SELECTED_PROBLEM_TYPE = "syncr:nothing-selected";

/**
 * Every type the client mints for a failure the api never answered.
 *
 * Named in one place because the api's half is a closed union now, so a minted document is only a
 * `Problem` if its type is declared: collecting them here is what keeps the two vocabularies
 * legible as two.
 */
export type ClientProblemType =
  | typeof UNEXPECTED_PROBLEM_TYPE
  | typeof UNREACHABLE_PROBLEM_TYPE
  | typeof NOTHING_SELECTED_PROBLEM_TYPE;

/**
 * A problem document whatever minted it: the api's contract, or the client itself.
 *
 * NOTHING MAY SWITCH ON `type` AS IF IT WERE EXHAUSTIVE. The api renders one type its document
 * does not publish -- the handler for a status no error class claims -- so a value outside this
 * union can arrive. It is still declared as the union rather than as a string, because the union
 * is what the generated client hands back, and restating the unpublished type here would put a
 * second copy of a server constant in the tree with nothing crossing the two.
 */
export type Problem = Omit<ApiProblem, "type"> & {
  type: ApiProblem["type"] | ClientProblemType;
};

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
