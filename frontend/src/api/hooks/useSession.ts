/* The session, read through the generated client.
 *
 * A 401 is an ANSWER, not a failure: the api answers `syncr:unauthorized` when no session is
 * presented, when the presented one has expired, and when a token is replayed after logout. All
 * three mean the same thing to the gate, which is that the reader has to sign in again.
 *
 * Every other failure is an error, and it must not read as "signed out". A 403
 * `syncr:origin-rejected` says the request's origin is not one this deployment serves, and a 500
 * or an unreachable api says nothing about the credential at all. Redirecting on any of those
 * would send a signed-in reader through the login flow and lose their place. */

import useSWR from "swr";

import { client } from "../client";
import { sessionKey } from "../keys";
import {
  toProblem,
  toResource,
  unreachableProblem,
  type Problem,
  type Resource,
} from "../../contract";
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
