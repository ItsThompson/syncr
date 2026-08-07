/* The backlog, and the two writes the Backlog screen and the global capture make on it.
 *
 * THREE HOOKS RATHER THAN ONE, because a read and two writes have three different shapes. What they share is
 * which keys they invalidate: both writes change the list under every filter, so each names
 * `isBacklogKey` rather than the one key the screen happens to be reading.
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
 * NO WRITE IS OPTIMISTIC. A capture's answer includes the server's own defaults, its identifier and its place
 * in the ordering; a completion's answer changes the header's counts and can change which OTHER rows are
 * marked, because the verdict is recomputed over a backlog one task lighter. Neither is predictable here, and
 * an optimistic row that guessed either would have to be corrected in a second redraw. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { backlogKey, isBacklogKey, type BacklogFilters } from "../keys";
import { apply, read } from "./request";
import { useWrite, type Write } from "./useWrite";
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
 * The query the client sends, built from the filters the screen holds.
 *
 * `openapi-fetch` is given only the members that are set, because under `exactOptionalPropertyTypes` an
 * explicit undefined is not the same as an absent parameter, and a filter sent empty is a filter the route
 * would have to interpret.
 */
function queryOf(filters: BacklogFilters): Record<string, string | boolean> {
  return {
    ...(filters.areaId === undefined ? {} : { areaId: filters.areaId }),
    ...(filters.status === undefined ? {} : { status: filters.status }),
    ...(filters.atRisk === undefined ? {} : { atRisk: filters.atRisk }),
  };
}

async function readBacklog(filters: BacklogFilters): Promise<Backlog> {
  const { header, tasks } = await read(() =>
    client.GET("/api/v1/tasks", { params: { query: queryOf(filters) } }),
  );
  return { header, tasks };
}

export function useBacklog(filters: BacklogFilters = {}): Resource<Backlog> {
  return toResource(useSWR<Backlog, Problem>(backlogKey(filters), () => readBacklog(filters)));
}

/**
 * Capturing a task, which is the one write reachable from every screen.
 *
 * The body is the request shape itself rather than a flattened set of parameters, so the two required
 * members and every documented default are the api's own contract at the call site.
 */
export function useTaskCapture(): Write<TaskCaptureBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: TaskCaptureBody) => {
    const refusal = await apply(() => client.POST("/api/v1/tasks", { body }));
    if (refusal !== null) return refusal;
    await mutate(isBacklogKey);
    return null;
  });
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
      client.POST("/api/v1/tasks/{task_id}/complete", { params: { path: { task_id: taskId } } }),
    );
    if (refusal !== null) return refusal;
    await mutate(isBacklogKey);
    return null;
  });
}
