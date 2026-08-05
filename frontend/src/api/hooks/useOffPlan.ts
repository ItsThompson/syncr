/* Off-plan periods: the spans a tenant has declared off, and the three writes over them.
 *
 * `keepFrame` IS EDITABLE AFTER DECLARATION, which is why there is a patch as well as a declaration. The
 * choice is presented when the span is declared and changed afterwards without redeclaring it, because the two
 * readings, a holiday abroad and a quiet week at home, are a decision a reader revises.
 *
 * A PATCH CARRIES ITS ROW'S ID BESIDE THE BODY rather than being bound at the hook. The panel renders a list
 * and every row is editable, so binding the id at the hook would mean one hook per row. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { offPlanKey } from "../keys";
import { apply, read } from "./request";
import { useWrite, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type OffPlanPeriod = components["schemas"]["OffPlanPeriodResponse"];
export type OffPlanCreateBody = components["schemas"]["OffPlanCreateRequest"];
export type OffPlanPatchBody = components["schemas"]["OffPlanPatchRequest"];

/** One row's identifier and the change to apply to it. */
export interface OffPlanEdit {
  readonly periodId: string;
  readonly patch: OffPlanPatchBody;
}

export interface OffPlanRemoval {
  readonly periodId: string;
}

async function readOffPlanPeriods(): Promise<readonly OffPlanPeriod[]> {
  const { periods } = await read(() => client.GET("/api/v1/off-plan"));
  return periods;
}

export function useOffPlanPeriods(): Resource<readonly OffPlanPeriod[]> {
  return toResource(useSWR<readonly OffPlanPeriod[], Problem>(offPlanKey(), readOffPlanPeriods));
}

/** Declaring a span off. A 409 naming the overlapping period is the interesting refusal. */
export function useOffPlanDeclaration(): Write<OffPlanCreateBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: OffPlanCreateBody) => {
    const refusal = await apply(() => client.POST("/api/v1/off-plan", { body }));
    if (refusal !== null) return refusal;
    await mutate(offPlanKey());
    return null;
  });
}

export function useOffPlanEdit(): Write<OffPlanEdit> {
  const { mutate } = useSWRConfig();

  return useWrite(async ({ periodId, patch }: OffPlanEdit) => {
    const refusal = await apply(() =>
      client.PATCH("/api/v1/off-plan/{period_id}", {
        params: { path: { period_id: periodId } },
        body: patch,
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(offPlanKey());
    return null;
  });
}

export function useOffPlanRemoval(): Write<OffPlanRemoval> {
  const { mutate } = useSWRConfig();

  return useWrite(async ({ periodId }: OffPlanRemoval) => {
    const refusal = await apply(() =>
      client.DELETE("/api/v1/off-plan/{period_id}", {
        params: { path: { period_id: periodId } },
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(offPlanKey());
    return null;
  });
}
