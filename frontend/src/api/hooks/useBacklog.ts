/* The backlog: the read the Backlog screen draws, and the completion it writes.
 *
 * TWO HOOKS RATHER THAN ONE, because a read and a write have two different shapes. What they share with the
 * capture in `useTaskCapture` is which keys they invalidate: every write changes the list under every filter, so
 * each names `isBacklogKey` rather than the one key the screen happens to be reading.
 *
 * THE CAPTURE IS NOT HERE. It sends a second request of its own, against a task's preference rather than against
 * this list, so it lives in `useTaskCapture` with the ordering that pair needs. `TaskCaptureBody` stays here,
 * because the shape a capture sends is this resource's own.
 *
 * THE AT-RISK MARK IS THE SERVER'S AND THIS FILE COMPUTES NOTHING. `atRisk` arrives on the row, derived from
 * the current week's verdict by the same collaborator the Week screen's read uses, so a task cannot be at risk
 * on one screen and fine on another. There is deliberately no comparison of a deadline against a capacity
 * anywhere in the frontend.
 *
 * NOTHING POLLS AND NOTHING IS PUSHED FOR IT. The determination is recomputed on every read, so it is current
 * whenever the plan changed and current again on the next read after time alone moved the verdict. There is no
 * `refreshInterval` here and the event stream carries no verdict member, because only a conflict notifies.
 * What re-reads the list is a write on it, which is exactly when this client can know something moved.
 *
 * NO WRITE ON THIS LIST IS OPTIMISTIC. A completion's answer changes the header's counts and can change which
 * OTHER rows are marked, because the verdict is recomputed over a backlog one task lighter. That is not
 * predictable here, and an optimistic row that guessed it would have to be corrected in a second redraw. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { backlogKey, backlogQuery, isBacklogKey, type BacklogFilters } from "../keys";
import { apply, read } from "./request";
import { idempotentHeaders, useWrite, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type BacklogTask = components["schemas"]["BacklogTaskResponse"];
export type BacklogHeader = components["schemas"]["BacklogHeader"];
export type TaskCaptureBody = components["schemas"]["TaskCreateRequest"];
export type TaskStatus = components["schemas"]["TaskStatus"];
export type { BacklogFilters };

export interface Backlog {
  /** The two figures the header states, over the Area's open tasks whatever the filters select. */
  readonly header: BacklogHeader;
  readonly tasks: readonly BacklogTask[];
}

/**
 * The query the client sends, which is the same enumeration the cache key is built from.
 *
 * `backlogQuery` lives beside the key deliberately: the two have to agree, because a key carrying a filter the
 * request did not send would cache one answer under another question. Two spellings of one filter set is how a
 * fourth filter comes to be added in one of them.
 */
async function readBacklog(filters: BacklogFilters): Promise<Backlog> {
  const { header, tasks } = await read(() =>
    client.GET("/api/v1/tasks", { params: { query: backlogQuery(filters) } }),
  );
  return { header, tasks };
}

export function useBacklog(filters: BacklogFilters = {}): Resource<Backlog> {
  return toResource(useSWR<Backlog, Problem>(backlogKey(filters), () => readBacklog(filters)));
}

/**
 * Completing a task. It leaves solver eligibility immediately and keeps its recorded time.
 *
 * THE WEEK'S KEY IS NOT INVALIDATED, and that is the honest choice rather than an omission. Completing a task
 * changes no block of the plan of record: the blocks bound to it become empty space in the NEXT solve, which
 * the mutation's version bump is what causes. Refetching the week here would redraw the same plan and imply
 * something had changed in it.
 */
export function useTaskCompletion(): Write<string> {
  const { mutate } = useSWRConfig();

  return useWrite(async (taskId: string) => {
    const refusal = await apply(() =>
      client.POST("/api/v1/tasks/{task_id}/complete", {
        params: { path: { task_id: taskId } },
        headers: idempotentHeaders(),
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(isBacklogKey);
    return null;
  });
}
