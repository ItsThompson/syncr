/* Day types, day shapes, and the entries one shape holds.
 *
 * FOUR HOOKS RATHER THAN ONE, because they are four resources and a screen renders them at four
 * different moments: the day types fill a select, the shapes fill a list, one shape's entries fill a
 * table, and the write declares an entry. One hook handing back all of that would put a shape's entries
 * behind the day types' loading state.
 *
 * THE LIST DOES NOT CARRY THE ENTRIES. `TemplateSummary` states a count and the entries are read per
 * shape, so a shape read is a real read and `useDayShape(null)` is a real answer rather than a request
 * with no identifier. That is why it is `Resource<Shape | null>`: nothing selected is a state the screen
 * renders an empty surface for, not a read that never lands.
 *
 * AN ENTRY'S CONTENT IS DECLARED ONCE. The api's patch shape carries the span alone, because a
 * materialized entry is keyed by its identifier and the local date, so rebinding one in place would
 * leave stored outcomes attributing an identity to content it no longer holds. Rebinding is therefore
 * remove-and-declare, and this file offers the declaration. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { dayShapeKey, dayShapesKey, dayTypesKey } from "../keys";
import { apply, read } from "./request";
import { useWrite, nothingSelectedProblem, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type DayType = components["schemas"]["DayTypeResponse"];
export type DayShapeSummary = components["schemas"]["TemplateSummary"];
export type DayShape = components["schemas"]["TemplateResponse"];
export type TemplateEntry = components["schemas"]["TemplateEntryResponse"];

/** The two shapes an entry is declared in. The `kind` member is what tells them apart on the wire. */
export type EntryBody =
  components["schemas"]["ConcreteEntryRequest"] | components["schemas"]["SlotEntryRequest"];

async function readDayTypes(): Promise<readonly DayType[]> {
  const { dayTypes } = await read(() => client.GET("/api/v1/day-types"));
  return dayTypes;
}

async function readDayShapes(): Promise<readonly DayShapeSummary[]> {
  const { templates } = await read(() => client.GET("/api/v1/templates"));
  return templates;
}

async function readDayShape(templateId: string): Promise<DayShape> {
  return read(() =>
    client.GET("/api/v1/templates/{template_id}", {
      params: { path: { template_id: templateId } },
    }),
  );
}

export function useDayTypes(): Resource<readonly DayType[]> {
  return toResource(useSWR<readonly DayType[], Problem>(dayTypesKey(), readDayTypes));
}

export function useDayShapes(): Resource<readonly DayShapeSummary[]> {
  return toResource(useSWR<readonly DayShapeSummary[], Problem>(dayShapesKey(), readDayShapes));
}

/** The selected shape and its entries. Ready with null when nothing is selected. */
export function useDayShape(templateId: string | null): Resource<DayShape | null> {
  const result = useSWR<DayShape, Problem>(
    templateId === null ? null : dayShapeKey(templateId),
    templateId === null ? null : () => readDayShape(templateId),
  );
  if (templateId === null) return { status: "ready", data: null };
  return toResource(result);
}

/**
 * Declaring one entry on one shape.
 *
 * Two keys are invalidated and both are named: the shape, because it holds the entries, and the list,
 * because its row states a count this changes. A blanket revalidation would refetch the habits, the
 * anchor types and every Area on a screen with no animation to hide the flicker.
 */
export function useEntryDeclaration(templateId: string | null): Write<EntryBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: EntryBody) => {
    if (templateId === null) return nothingSelectedProblem("day shape", "list");
    const refusal = await apply(() =>
      client.POST("/api/v1/templates/{template_id}/entries", {
        params: { path: { template_id: templateId } },
        body,
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(dayShapeKey(templateId));
    await mutate(dayShapesKey());
    return null;
  });
}
