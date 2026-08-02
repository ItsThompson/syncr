/* The api's own readiness, read through the generated client.
 *
 * `not ready` is an ANSWER, not a failure: the endpoint returns 503 with the reason while the
 * database is unreachable or a migration has not been applied, and that is exactly the
 * reading the shell renders. Only a response the contract does not describe, or a request
 * that never arrives, is an error. */

import useSWR from "swr";

import { client } from "../client";
import { readinessKey } from "../keys";
import { toProblem, unreachableProblem, type Problem } from "../problem";
import { toResource, type Resource } from "../resource";

export interface Readiness {
  readonly isReady: boolean;
}

const READY = 200;
const NOT_READY = 503;

async function readReadiness(): Promise<Readiness> {
  const { error, response } = await client.GET("/readyz").catch((cause: unknown) => {
    throw unreachableProblem(cause);
  });
  if (response.status === READY || response.status === NOT_READY) {
    return { isReady: response.status === READY };
  }
  throw toProblem(error, response);
}

export function useReadiness(): Resource<Readiness> {
  return toResource(useSWR<Readiness, Problem>(readinessKey(), readReadiness));
}
