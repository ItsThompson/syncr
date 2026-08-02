/* The api's own readiness, read through the generated client.
 *
 * `not ready` is an ANSWER, not a failure: the endpoint returns 503 with the reason while the
 * database is unreachable or a migration has not been applied, and that is exactly the reading the
 * shell renders. Only a response the contract does not describe, or a request that never arrives,
 * is an error.
 *
 * Both statuses are declared in the document and both carry the same model, so the reading comes
 * from the body rather than from a status code this file would otherwise have to know. `checks` is
 * carried through unchanged: it is the payload that says WHICH capability is unavailable, which is
 * what a degradation notice has to name. */

import useSWR from "swr";

import { client } from "../client";
import { readinessKey } from "../keys";
import {
  toProblem,
  toResource,
  unreachableProblem,
  type Problem,
  type Resource,
} from "../../contract";
import type { components } from "../schema";

type ReadinessReading = components["schemas"]["ReadinessReading"];

const READINESS_STATUSES = new Set(["ready", "not_ready"]);

/* Discriminated on the two literal values, not on the presence of a `status` field. A Problem also
 * carries `status`, as a NUMBER, so a 500's problem document would otherwise satisfy a
 * presence check and be read as `not ready`: a fault reported as a healthy answer. */
function isReadinessReading(value: unknown): value is ReadinessReading {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as { status?: unknown; checks?: unknown };
  if (typeof candidate.status !== "string") return false;
  if (!READINESS_STATUSES.has(candidate.status)) return false;
  return typeof candidate.checks === "object" && candidate.checks !== null;
}

export interface Readiness {
  readonly isReady: boolean;
  /** Per-check outcomes, keyed by the check's own name. */
  readonly checks: ReadinessReading["checks"];
}

/** The names of the checks that are not ready, in the order the api reported them. */
export function unreadyChecks(readiness: Readiness): string[] {
  return Object.entries(readiness.checks)
    .filter(([, reading]) => !reading.ok)
    .map(([name]) => name);
}

async function readReadiness(): Promise<Readiness> {
  const { data, error, response } = await client.GET("/readyz").catch((cause: unknown) => {
    throw unreachableProblem(cause);
  });

  /* A 503 declares the same model as a 200, so openapi-fetch routes its body to `error`. Both are
   * readings; neither is a failure. */
  const reading = data ?? error;
  if (!isReadinessReading(reading)) throw toProblem(error, response);

  return { isReady: reading.status === "ready", checks: reading.checks };
}

export function useReadiness(): Resource<Readiness> {
  return toResource(useSWR<Readiness, Problem>(readinessKey(), readReadiness));
}
