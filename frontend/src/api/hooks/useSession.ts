/* The session, read through the generated client.
 *
 * A 401 is an ANSWER, not a failure: it is what the api returns when no session is presented or
 * the presented one has stopped working, which is exactly the state the gate exists to act on.
 * Any other failure is an error, and it must not read as "signed out": redirecting to sign-in
 * because the api was briefly unreachable would send a signed-in user through the login flow for
 * a network blip. */

import useSWR from "swr";

import { client } from "../client";
import { sessionKey } from "../keys";
import { toProblem, unreachableProblem, type Problem } from "../problem";
import { toResource, type Resource } from "../resource";
import type { components } from "../schema";

/** Null when no session is presented, which the api reports as 401. */
export type Session = components["schemas"]["SessionResponse"] | null;

const SIGNED_OUT = 401;

async function readSession(): Promise<Session> {
  const { data, error, response } = await client.GET("/auth/session").catch((cause: unknown) => {
    throw unreachableProblem(cause);
  });
  if (response.status === SIGNED_OUT) return null;
  if (data === undefined) throw toProblem(error, response);
  return data;
}

export function useSession(): Resource<Session> {
  return toResource(useSWR<Session, Problem>(sessionKey(), readSession));
}
