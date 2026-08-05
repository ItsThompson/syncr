/* The two things every hook in this directory does with the generated client, stated once.
 *
 * `read` throws a `Problem`, `apply` returns one, and `answered` returns the body beside it. The asymmetry is the
 * point rather than an inconsistency. SWR wants a fetcher that rejects, because a rejection is what puts a hook
 * into its error state. A form wants a value, because a rejection it has to catch is a rejection it can drop:
 * the 422 naming which member to change is the most useful thing the api says on a write path, and it has to
 * reach the row the reader is looking at. And a write whose own response the caller renders needs both halves,
 * which is `answered`.
 *
 * `apply` IS NOT `answered` WITH THE BODY DROPPED, which is the shape it looks like. A `204` carries no body and
 * no error, so a function that read absence of body as failure would report every successful removal as refused.
 * Each states its own test: `apply` reads the error, `answered` reads the body.
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

/** The body a 2xx carried, or the problem that refused it. Exactly one member is null. */
export type Answered<T> =
  { readonly body: T; readonly problem: null } | { readonly body: null; readonly problem: Problem };

/**
 * The body or the problem, for a write whose RESPONSE the caller needs.
 *
 * NOT WHAT `apply` IS BUILT FROM, and the reason is worth stating because the two look like one function. They ask
 * different questions: this one asks what body came back, and `apply` asks whether anything refused. A `204` has no
 * body and no error, so expressing `apply` in terms of this would report every successful removal as a refusal.
 *
 * The one caller is a write that mints a value it then renders: starting a Google connect signs a state parameter
 * and answers with the consent surface, so a caller that dropped the body would have to ask again and mint a
 * second one. Neither throwing nor discarding fits that, which is why there are three functions here rather than
 * two.
 */
export async function answered<T>(send: () => Promise<Answer<T>>): Promise<Answered<T>> {
  try {
    const { data, error, response } = await send();
    if (data === undefined) return { body: null, problem: toProblem(error, response) };
    return { body: data, problem: null };
  } catch (cause) {
    return { body: null, problem: unreachableProblem(cause) };
  }
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
