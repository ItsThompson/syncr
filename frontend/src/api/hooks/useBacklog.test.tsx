/* THE BACKLOG HOOKS: which request each read builds, and which keys each write invalidates.
 *
 * THE KEY CARRIES THE FILTERS BECAUSE TWO FILTERS ARE TWO RESOURCES. A read narrowed to the rows the week's
 * verdict marks must not be handed back for the whole list, and the narrowing is the server's determination
 * rather than something a client can reproduce.
 *
 * A WRITE INVALIDATES EVERY BACKLOG KEY AND NOTHING ELSE. That is not a blanket revalidation: one resource has
 * several keys because the filters are in them, and a capture changes the list under all of them. What must NOT
 * be invalidated is a week, which is asserted by counting a read that does not run.
 *
 * NOTHING POLLS. `US-TASK-03` says the at-risk determination is recomputed on every read rather than on a timer
 * and that nothing pushes it, so a hook with a refresh interval would be the defect: the clock is advanced here
 * and the read count is asserted not to move. */

import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";

import { apiServer } from "../../testing/apiServer";
import { countedHandler, recordingHandler } from "../../testing/apiStub";
import { FreshCache } from "../../testing/renderRoute";
import { backlogKey, isBacklogKey, weekKey } from "../keys";
import { useBacklog, useTaskCapture, useTaskCompletion } from "./useBacklog";

const origin = window.location.origin;
const TASK_ID = "7c2d1a10-0001-4a3b-8b21-000000000001";

const BACKLOG = {
  header: { openCount: 1, atRiskCount: 0 },
  tasks: [] as unknown[],
};

afterEach(() => {
  vi.useRealTimers();
});

/** Every query string the backlog was read with, in order. */
function recordingRead(): { readonly queries: string[] } {
  const queries: string[] = [];
  apiServer.use(
    http.get(`${origin}/api/v1/tasks`, ({ request }) => {
      queries.push(new URL(request.url).search.replace(/^\?/, ""));
      return HttpResponse.json(BACKLOG);
    }),
  );
  return { queries };
}

describe("the key the filters build", () => {
  it("is the bare path with no filter set, so it is the request the client sends", () => {
    expect(backlogKey()).toBe("/api/v1/tasks");
  });

  it("carries every filter that is set, and omits the ones that are not", () => {
    expect(backlogKey({ status: "open" })).toBe("/api/v1/tasks?status=open");
    expect(backlogKey({ areaId: "a1", status: "open", atRisk: true })).toBe(
      "/api/v1/tasks?areaId=a1&status=open&atRisk=true",
    );
    expect(backlogKey({ atRisk: false })).toBe("/api/v1/tasks?atRisk=false");
  });

  it("gives two filters two keys, so one read is never handed back for the other", () => {
    expect(backlogKey({ atRisk: true })).not.toBe(backlogKey({ atRisk: false }));
    expect(backlogKey({ atRisk: false })).not.toBe(backlogKey());
  });

  /* The `?` is load-bearing: a task read by identifier is a different resource, and a capture changes none of
     them, so a predicate matching the prefix alone would invalidate reads a write cannot have changed. */
  it("matches every backlog key and no single task's", () => {
    expect(isBacklogKey(backlogKey())).toBe(true);
    expect(isBacklogKey(backlogKey({ atRisk: true }))).toBe(true);
    expect(isBacklogKey(`/api/v1/tasks/${TASK_ID}`)).toBe(false);
    expect(isBacklogKey(weekKey("2026-W07"))).toBe(false);
    expect(isBacklogKey(undefined)).toBe(false);
  });
});

describe("reading the backlog", () => {
  it("sends the filters as the api's own query parameters", async () => {
    const read = recordingRead();

    const { result } = renderHook(() => useBacklog({ status: "open", atRisk: true }), {
      wrapper: FreshCache,
    });

    await waitFor(() => {
      expect(result.current.status).toBe("ready");
    });
    expect(read.queries).toEqual(["status=open&atRisk=true"]);
  });

  it("sends no parameters at all when no filter is set", async () => {
    const read = recordingRead();

    const { result } = renderHook(() => useBacklog(), { wrapper: FreshCache });

    await waitFor(() => {
      expect(result.current.status).toBe("ready");
    });
    expect(read.queries).toEqual([""]);
  });

  it("reads once and never again on a timer, because nothing pushes the marking either", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const read = recordingRead();

    const { result } = renderHook(() => useBacklog({ status: "open" }), { wrapper: FreshCache });
    await waitFor(() => {
      expect(result.current.status).toBe("ready");
    });

    await vi.advanceTimersByTimeAsync(30 * 60 * 1000);

    expect(read.queries).toHaveLength(1);
  });
});

describe("the writes", () => {
  it("captures with the body the caller built, and reads the list again", async () => {
    const capture = recordingHandler("post", "/api/v1/tasks", { status: 201, body: {} });
    const list = countedHandler("/api/v1/tasks", { status: 200, body: BACKLOG });
    apiServer.use(list.handler, capture.handler);
    const { result } = renderHook(
      () => ({ read: useBacklog({ status: "open" }), write: useTaskCapture() }),
      { wrapper: FreshCache },
    );
    await waitFor(() => {
      expect(result.current.read.status).toBe("ready");
    });
    expect(list.count()).toBe(1);

    const applied = await result.current.write.submit({
      areaId: "a1",
      title: "Kontron take-home",
      estimateMinutes: 30,
      minChunkMinutes: 15,
      deadline: null,
      priority: "normal",
      splittable: true,
    });

    expect(applied).toBe(true);
    expect(capture.bodies).toEqual([
      {
        areaId: "a1",
        title: "Kontron take-home",
        estimateMinutes: 30,
        minChunkMinutes: 15,
        deadline: null,
        priority: "normal",
        splittable: true,
      },
    ]);
    await waitFor(() => {
      expect(list.count()).toBe(2);
    });
  });

  it("keeps the refusal a capture was answered with, so a form can render it", async () => {
    apiServer.use(
      http.get(`${origin}/api/v1/tasks`, () => HttpResponse.json(BACKLOG)),
      http.post(`${origin}/api/v1/tasks`, () =>
        HttpResponse.json(
          {
            type: "syncr:validation-failed",
            title: "Validation failed",
            status: 422,
            detail: "One or more members were refused.",
            errors: [{ field: "title", message: "is too long" }],
          },
          { status: 422 },
        ),
      ),
    );
    const { result } = renderHook(() => useTaskCapture(), { wrapper: FreshCache });

    const applied = await result.current.submit({
      areaId: "a1",
      title: "x".repeat(400),
      estimateMinutes: 30,
      minChunkMinutes: 15,
      deadline: null,
      priority: "normal",
      splittable: true,
    });

    expect(applied).toBe(false);
    await waitFor(() => {
      expect(result.current.problem?.errors).toEqual([{ field: "title", message: "is too long" }]);
    });
  });

  /* A COMPLETION DOES NOT REFETCH THE WEEK. It changes no block of the plan of record: the blocks bound to the
     task become empty space in the NEXT solve, which the version bump is what causes. Refetching the week here
     would redraw the same plan and imply something in it had changed. */
  it("completes a task, reads the list again, and does not read the week", async () => {
    const list = countedHandler("/api/v1/tasks", { status: 200, body: BACKLOG });
    const week = countedHandler("/api/v1/weeks/2026-W07", { status: 200, body: {} });
    const complete = recordingHandler("post", `/api/v1/tasks/${TASK_ID}/complete`, {
      status: 200,
      body: {},
    });
    apiServer.use(list.handler, week.handler, complete.handler);
    const { result } = renderHook(
      () => ({ read: useBacklog({ status: "open" }), write: useTaskCompletion() }),
      { wrapper: FreshCache },
    );
    await waitFor(() => {
      expect(result.current.read.status).toBe("ready");
    });

    const applied = await result.current.write.submit(TASK_ID);

    expect(applied).toBe(true);
    expect(complete.bodies).toEqual([null]);
    await waitFor(() => {
      expect(list.count()).toBe(2);
    });
    expect(week.count()).toBe(0);
  });
});
