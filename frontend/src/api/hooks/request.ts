/* The two things every hook in this directory does with the generated client, stated once.
 *
 * `read` throws a `Problem` and `apply` returns one, and the asymmetry is the point rather than an
 * inconsistency. SWR wants a fetcher that rejects, because a rejection is what puts a hook into its
 * error state. A form wants a value, because a rejection it has to catch is a rejection it can drop:
 * the 422 naming which member to change is the most useful thing the api says on a write path, and it
 * has to reach the row the reader is looking at.
 *
 * Both take the CALL rather than a path, so the call site still names the route and still gets the
 * generated types for its parameters and its body. What is factored out is only the answer: a request
 * that never arrived is a `Problem` with no status, and a body the error contract does not describe is
 * a `Problem` synthesised from the response. Repeating that per hook is how one of them comes to read
 * an HTML error page as a value. */

import { toProblem, unreachableProblem, type Problem } from "../../contract";

/**
 * What `openapi-fetch` answers with: the parsed body, or the error body plus the response.
 *
 * Declared here rather than imported because the client's own result type is a discriminated union
 * per operation, and every arm of every one of them satisfies this shape.
 */
export interface Answer<T> {
  readonly data?: T | undefined;
  readonly error?: unknown;
  readonly response: Response;
}

/** The body a 2xx carried. Throws a `Problem` for anything else, which is what SWR reads. */
export async function read<T>(send: () => Promise<Answer<T>>): Promise<T> {
  const { data, error, response } = await send().catch((cause: unknown) => {
    throw unreachableProblem(cause);
  });
  if (data === undefined) throw toProblem(error, response);
  return data;
}

/** Null when the change was applied, or the problem that refused it. Never throws. */
export async function apply(send: () => Promise<Answer<unknown>>): Promise<Problem | null> {
  try {
    const { error, response } = await send();
    return error === undefined ? null : toProblem(error, response);
  } catch (cause) {
    return unreachableProblem(cause);
  }
}
