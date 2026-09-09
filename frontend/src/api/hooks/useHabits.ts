/* The habits a tenant has declared, with both derivations rendered beside each one.
 *
 * NEITHER DERIVATION IS SETTABLE AND THERE IS NO ROUTE THAT WOULD. The rotation cursor and the debt
 * figure are projections of the append-only outcome log, so `HabitPatchRequest` has no member for
 * either and an unknown field is refused. That is what makes the screen's read-only rendering of the
 * cursor a boundary the api holds rather than a discipline the form keeps: a control that set one would
 * have nothing to send.
 *
 * The Area is not patchable either. It is declared once, because moving it would re-attribute hours that
 * have already been reported. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { habitsKey } from "../keys";
import { apply, read } from "./request";
import { idempotentHeaders, useWrite, nothingSelectedProblem, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type Habit = components["schemas"]["HabitResponse"];
export type HabitEdit = components["schemas"]["HabitPatchRequest"];

async function readHabits(): Promise<readonly Habit[]> {
  const { habits } = await read(() => client.GET("/api/v1/habits"));
  return habits;
}

export function useHabits(): Resource<readonly Habit[]> {
  return toResource(useSWR<readonly Habit[], Problem>(habitsKey(), readHabits));
}

export function useHabitEdit(habitId: string | null): Write<HabitEdit> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: HabitEdit) => {
    if (habitId === null) return nothingSelectedProblem("habit", "table");
    const refusal = await apply(() =>
      client.PATCH("/api/v1/habits/{habit_id}", {
        params: { path: { habit_id: habitId } },
        headers: idempotentHeaders(),
        body,
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(habitsKey());
    return null;
  });
}
