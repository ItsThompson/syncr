/* Several reads, as one reading a screen can render.
 *
 * A hook answers for its own resource, which is right: a screen with six reads has six things that can be
 * outstanding or refused. What a SURFACE needs is one answer, because a table cannot draw two thirds of its
 * columns. So this narrows a set of resources to one discriminated reading, and it does it without losing
 * either the data's types or the name of the read that failed.
 *
 * THE RESOURCES ARRIVE NAMED, and that is the whole reason this takes an object rather than a list. A tuple
 * would answer "something did not arrive"; a name lets the surface say WHICH read failed, which is the
 * difference between a sentence a reader can act on and one they cannot.
 *
 * A REFUSAL OUTRANKS AN OUTSTANDING READ. If one resource has failed and another is still in flight, the
 * failure is the reading: the outstanding one may yet arrive, but the surface it would feed cannot be drawn
 * either way, and a reader waiting for a screen that will not appear learns nothing. `toResource` makes the
 * same choice one layer down, where an error outranks stale data.
 *
 * Pure: no React, no client, no DOM. */

import type { Problem, Resource } from "../contract";

export type Reading<Data extends Record<string, unknown>> =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly problem: Problem; readonly name: string }
  | { readonly status: "ready"; readonly data: Data };

/**
 * The reading a set of named resources amounts to.
 *
 * The returned `data` holds every resource's value under the name it was given, which is why the assembled
 * object is asserted rather than inferred: it is built key by key from the same object whose keys the type
 * came from, and the assertion is only reachable once every one of them is ready.
 */
export function readingOf<Data extends Record<string, unknown>>(resources: {
  readonly [Name in keyof Data]: Resource<Data[Name]>;
}): Reading<Data> {
  const ready: Record<string, unknown> = {};
  let isLoading = false;

  for (const [name, resource] of Object.entries(resources) as [string, Resource<unknown>][]) {
    if (resource.status === "error") return { status: "error", problem: resource.problem, name };
    if (resource.status === "loading") isLoading = true;
    else ready[name] = resource.data;
  }

  if (isLoading) return { status: "loading" };
  return { status: "ready", data: ready as Data };
}
