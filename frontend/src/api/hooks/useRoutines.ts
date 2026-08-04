/* The routines a tenant has declared: the frame of the day.
 *
 * Read here for one reason, which is that a concrete template entry names a routine or a habit and the
 * form offering that choice needs both lists by name. Nothing on this screen edits a routine: the
 * circadian frame is authored where a routine lives, and a shape that could rename one would be a
 * second home for the same value. */

import useSWR from "swr";

import { client } from "../client";
import { routinesKey } from "../keys";
import { read } from "./request";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type Routine = components["schemas"]["RoutineResponse"];

async function readRoutines(): Promise<readonly Routine[]> {
  const { routines } = await read(() => client.GET("/api/v1/routines"));
  return routines;
}

export function useRoutines(): Resource<readonly Routine[]> {
  return toResource(useSWR<readonly Routine[], Problem>(routinesKey(), readRoutines));
}
