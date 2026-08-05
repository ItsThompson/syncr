/* A write double: the seam between a form and the api, with the bodies it was handed.
 *
 * THE FORM'S CONTRACT IS THE BODY IT SUBMITS, so this is what a form test asserts against. Driving the same
 * assertion through the network would test the client, the key registry and the interceptor as well, and would
 * say nothing more about the form: what it can get wrong is which members it puts in the body and whether it
 * sends one at all.
 *
 * The refusal is a constructor argument rather than something to set later, because a form rendering a refusal
 * renders it from the first paint: `problem` is the LAST refusal, and there is no moment at which a form has
 * submitted and is waiting. */

import { vi } from "vitest";

import type { Problem } from "../../../contract";
import type { Write } from "../../../api/hooks/useWrite";

export interface WriteDouble<Body> {
  readonly write: Write<Body>;
  /** Every body submitted, in order. */
  readonly bodies: Body[];
}

/** The submit, typed so the double and the seam it stands in for cannot drift. */
type Submit<Body> = (body: Body) => Promise<boolean>;

export function writeDouble<Body>(problem: Problem | null = null): WriteDouble<Body> {
  const bodies: Body[] = [];
  const submit = vi.fn<Submit<Body>>(async (body) => {
    bodies.push(body);
    return problem === null;
  });
  /* `clear` is a no-op here rather than mutable state: the double stands in for the SEAM, and what a form can
   * get wrong is the body it submits. Which caller forgets a refusal is the route's decision, asserted where
   * the route is. */
  return { write: { submit, problem, clear: () => {} }, bodies };
}
