/* The routines a tenant has declared: the frame of the day.
 *
 * The list is read for one reason, which is that a concrete template entry names a routine or a habit and
 * the form offering that choice needs both lists by name.
 *
 * THE EDIT IS GENERIC AND SO IS ITS CALLER. `PATCH /api/v1/routines/{id}` is where a routine's floor lives,
 * as `minDurationMinutes`, and the Settings screen renders one control per routine that calls it. The floor is
 * a field on every routine, so naming a routine in this layer would put a screen's framing in the api layer.
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
 * `null` is a real argument, and no caller passes one today: every screen that offers this write has a routine to
 * address before it renders a control. The branch stays because the argument is the routine's id rather than the
 * hook's caller, so a screen that offers the write from a selection can pass nothing selected, and a control that
 * did nothing and said nothing would be worse than the refusal. Its own case is what exercises it.
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
