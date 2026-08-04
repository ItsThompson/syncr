/* The anchor types, in evaluation order, and the two writes that change them.
 *
 * ORDER IS THE RESOURCE'S OWN STATE. Rules evaluate in the order the list arrives in and the first match
 * wins, so the list is never re-sorted here: a table that ordered its own rows by name would show a
 * reader the wrong answer to the only question the order settles.
 *
 * REORDERING IS A WHOLE-ORDER PUT. A partial order would leave the types it does not name at positions
 * the caller cannot see, and first-match semantics make that a silent change to what every one of them
 * matches. Both writes invalidate the same one key, because both change the same one collection. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { anchorTypesKey } from "../keys";
import { apply, read } from "./request";
import { useWrite, nothingSelectedProblem, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type AnchorType = components["schemas"]["AnchorTypeResponse"];
export type AnchorTypeEdit = components["schemas"]["AnchorTypePatchRequest"];
export type AnchorTypeOrder = components["schemas"]["ReorderAnchorTypesRequest"];

async function readAnchorTypes(): Promise<readonly AnchorType[]> {
  const { anchorTypes } = await read(() => client.GET("/api/v1/anchor-types"));
  return anchorTypes;
}

export function useAnchorTypes(): Resource<readonly AnchorType[]> {
  return toResource(useSWR<readonly AnchorType[], Problem>(anchorTypesKey(), readAnchorTypes));
}

export function useAnchorTypeEdit(anchorTypeId: string | null): Write<AnchorTypeEdit> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: AnchorTypeEdit) => {
    if (anchorTypeId === null) return nothingSelectedProblem("anchor type", "table");
    const refusal = await apply(() =>
      client.PATCH("/api/v1/anchor-types/{anchor_type_id}", {
        params: { path: { anchor_type_id: anchorTypeId } },
        body,
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(anchorTypesKey());
    return null;
  });
}

export function useAnchorTypeOrder(): Write<AnchorTypeOrder> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: AnchorTypeOrder) => {
    const refusal = await apply(() => client.PUT("/api/v1/anchor-types/order", { body }));
    if (refusal !== null) return refusal;
    await mutate(anchorTypesKey());
    return null;
  });
}
