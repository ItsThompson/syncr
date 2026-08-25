/* THE WEEK SCREEN'S OTHER FOUR WRITES: a tradeoff, an approval, a rejected move, and an answered conflict.
 *
 * EACH INVALIDATES THE WEEK AND NOTHING ELSE, because each changes one week: a blanket revalidation would refetch a
 * whole plan because a setting changed, which is slow and is a source of flicker on a surface with no animation to
 * hide it.
 *
 * REQUESTING A TRADEOFF MUTATES NOTHING. It dispatches a solve against modified inputs and the candidate rides on the
 * operation; the result lands in the pending slot as a proposal, and the plan of record is untouched until the reader
 * approves it. That is why the control says `Propose`: the concession becomes real in the approval transaction and
 * nowhere else.
 *
 * EVERY WRITE TO A GUARDED ROUTE SENDS AN `Idempotency-Key`. The approval route DEMANDS it -- omitting it is a 400 --
 * and the reject and the conflict resolution send it for the reason every guarded write in this api does: a retry must
 * not become a second act. The tradeoff request sends none, because its route reads no key; the writing layer
 * (`useWrite`) owns both the rule and the header, and no call site here states either. The key is untyped wherever it
 * travels, because the api reads it off the request object rather than declaring it as a parameter, so it is absent
 * from the document every generated client is built from.
 *
 * REJECTING A PROPOSED MOVE IS A PIN, not a rejection concept of its own: it pins the block where the plan of record
 * already holds it and re-solves, so the rest of the proposal is recomputed rather than preserved. Once the rejected
 * block is fixed, a different arrangement of the remainder may well be better. */

import { useSWRConfig } from "swr";

import { client } from "../client";
import { weekKey } from "../keys";
import { answered, apply } from "./request";
import { idempotentHeaders, useWrite, type Write } from "./useWrite";
import type { components } from "../schema";

type AdjustmentKind = components["schemas"]["AdjustmentKind"];
type ConflictResolution = components["schemas"]["ConflictResolution"];
type Operation = components["schemas"]["OperationResponse"];

export interface TradeoffRequest {
  readonly kind: AdjustmentKind;
  /** The task, routine or Area the concession would act on. One this week's verdict offers that kind for. */
  readonly targetId: string;
}

export interface RejectMoveRequest {
  readonly blockId: string;
}

export interface ResolveConflictRequest {
  readonly conflictId: string;
  readonly resolution: ConflictResolution;
  /** The type to apply, stated only with `retyped`, and null there to leave the commitment as opaque busy time. */
  readonly anchorTypeId?: string | null | undefined;
}

/**
 * The four writes.
 *
 * Three of them answer with an operation, and it is handed to `onOperation` rather than returned: the caller that
 * tracks an operation is the operation hook, and a second copy of the record here would be a second answer to "what
 * is in flight for this week".
 */
export interface WeekWrites {
  readonly requestTradeoff: Write<TradeoffRequest>;
  readonly approve: Write<void>;
  readonly rejectMove: Write<RejectMoveRequest>;
  readonly resolveConflict: Write<ResolveConflictRequest>;
}

export function useWeekWrites(isoWeek: string, onOperation?: (one: Operation) => void): WeekWrites {
  const { mutate } = useSWRConfig();
  const path = { iso_week: isoWeek };

  const requestTradeoff = useWrite(async ({ kind, targetId }: TradeoffRequest) => {
    const { body, problem } = await answered(() =>
      client.POST("/api/v1/weeks/{iso_week}/tradeoffs", {
        params: { path },
        body: { kind, targetId },
      }),
    );
    if (problem !== null) return problem;
    onOperation?.(body);
    return null;
  });

  const approve = useWrite(async () => {
    const { body, problem } = await answered(() =>
      client.POST("/api/v1/weeks/{iso_week}/approve", {
        params: { path },
        headers: idempotentHeaders(),
      }),
    );
    if (problem !== null) return problem;
    /* The approval bumps the input version and enqueues a projection, so the week is read again: the pending slot is
     * now empty and the plan of record is the approved document. */
    onOperation?.(body.projection);
    await mutate(weekKey(isoWeek));
    return null;
  });

  const rejectMove = useWrite(async ({ blockId }: RejectMoveRequest) => {
    const { body, problem } = await answered(() =>
      client.POST("/api/v1/weeks/{iso_week}/reject-block", {
        params: { path },
        headers: idempotentHeaders(),
        body: { blockId },
      }),
    );
    if (problem !== null) return problem;
    onOperation?.(body.operation);
    await mutate(weekKey(isoWeek));
    return null;
  });

  const resolveConflict = useWrite(
    async ({ conflictId, resolution, anchorTypeId }: ResolveConflictRequest) => {
      const refusal = await apply(() =>
        client.POST("/api/v1/conflicts/{conflict_id}/resolve", {
          params: { path: { conflict_id: conflictId } },
          headers: idempotentHeaders(),
          body: { resolution, ...(anchorTypeId === undefined ? {} : { anchorTypeId }) },
        }),
      );
      if (refusal !== null) return refusal;
      await mutate(weekKey(isoWeek));
      return null;
    },
  );

  return { requestTradeoff, approve, rejectMove, resolveConflict };
}
