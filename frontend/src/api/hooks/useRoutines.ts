/* The routines a tenant has declared: the frame of the day.
 *
 * The list is read for one reason, which is that a concrete template entry names a routine or a habit and
 * the form offering that choice needs both lists by name.
 *
 * THE EDIT IS GENERIC AND ITS ONE CALLER IS NOT. `PATCH /api/v1/routines/{id}` is where the sleep floor
 * lives, as `minDurationMinutes`, and the Settings screen renders a control labeled as the sleep floor that
 * calls it. The hook stays a routine edit rather than becoming a sleep-floor edit, because the floor is a
 * field on every routine and naming one caller in the hook would put the screen's framing in the api layer.
 * There is no settings field for the value and there is no second write here that could become one. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { routinesKey } from "../keys";
import { apply, read } from "./request";
import { useWrite, nothingSelectedProblem, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type Routine = components["schemas"]["RoutineResponse"];
export type RoutinePatchBody = components["schemas"]["RoutinePatchRequest"];

async function readRoutines(): Promise<readonly Routine[]> {
  const { routines } = await read(() => client.GET("/api/v1/routines"));
  return routines;
}

export function useRoutines(): Resource<readonly Routine[]> {
  return toResource(useSWR<readonly Routine[], Problem>(routinesKey(), readRoutines));
}

/**
 * Changing one routine's span. The list is the only key it invalidates, because the list is the only read.
 *
 * `null` is a real argument: a screen offering the sleep floor before the sleep routine has been declared
 * has no row to patch, and a control that did nothing and said nothing would be worse than the refusal.
 */
export function useRoutineEdit(routineId: string | null): Write<RoutinePatchBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: RoutinePatchBody) => {
    if (routineId === null) return nothingSelectedProblem("routine", "list of routines");
    const refusal = await apply(() =>
      client.PATCH("/api/v1/routines/{routine_id}", {
        params: { path: { routine_id: routineId } },
        body,
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(routinesKey());
    return null;
  });
}
