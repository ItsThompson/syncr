/* THE BACKLOG HOOKS: which request each read builds, and which keys each write invalidates.
 *
 * THE KEY CARRIES THE FILTERS BECAUSE TWO FILTERS ARE TWO RESOURCES. A read narrowed to the rows the week's
 * verdict marks must not be handed back for the whole list, and the narrowing is the server's determination
 * rather than something a client can reproduce.
 *
 * A WRITE INVALIDATES EVERY BACKLOG KEY AND NOTHING ELSE. That is not a blanket revalidation: one resource has
 * several keys because the filters are in them, and a write changes the list under all of them. What must NOT
 * be invalidated is a week, which is asserted by counting a read that does not run.
 *
 * NOTHING POLLS. The at-risk determination is recomputed on every read rather than on a timer, and nothing pushes
 * it, so a hook with a refresh interval would be the defect: the clock is advanced here and the read count is
 * asserted not to move.
 *
 * THE CAPTURE'S OWN CASES ARE IN `useTaskCapture.test.tsx`, with the second write it sends. */

import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import useSWR from "swr";

import { apiServer } from "../../testing/apiServer";
import { countedHandler, recordingHandler } from "../../testing/apiStub";
import { FreshCache } from "../../testing/renderRoute";
import { client } from "../client";
import { backlogKey, isBacklogKey, weekKey } from "../keys";
import { read as readBody } from "./request";
import { useBacklog, useTaskCompletion } from "./useBacklog";

const origin = window.location.origin;
const TASK_ID = "7c2d1a10-0001-4a3b-8b21-000000000001";
const ISO_WEEK = "2026-W07";

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

describe("the completion", () => {
  /* A COMPLETION DOES NOT REFETCH THE WEEK. It changes no block of the plan of record: the blocks bound to the
     task become empty space in the NEXT solve, which the version bump is what causes. Refetching the week here
     would redraw the same plan and imply something in it had changed.

     THE WEEK KEY HAS ITS OWN SUBSCRIBER IN THIS TEST, and that is the whole reason the assertion means anything:
     SWR revalidates a key nothing is subscribed to by not reading it at all, so a count taken without a
     subscriber is pinned to zero whatever the write invalidates. With the subscriber mounted, adding
     `mutate(weekKey(...))` to the hook turns this red. */
  it("completes a task, reads the list again, and does not read the week", async () => {
    const list = countedHandler("/api/v1/tasks", { status: 200, body: BACKLOG });
    const week = countedHandler(`/api/v1/weeks/${ISO_WEEK}`, { status: 200, body: {} });
    const complete = recordingHandler("post", `/api/v1/tasks/${TASK_ID}/complete`, {
      status: 200,
      body: {},
    });
    apiServer.use(list.handler, week.handler, complete.handler);
    const { result } = renderHook(
      () => ({
        read: useBacklog({ status: "open" }),
        /* A bare subscriber on the week's own key, which is what makes the count able to move. Bare rather than
           `useWeek`, because what is under test is the KEY the write does or does not name. */
        weekRead: useSWR(weekKey(ISO_WEEK), () =>
          readBody(() =>
            client.GET("/api/v1/weeks/{iso_week}", { params: { path: { iso_week: ISO_WEEK } } }),
          ),
        ),
        write: useTaskCompletion(),
      }),
      { wrapper: FreshCache },
    );
    await waitFor(() => {
      expect(result.current.read.status).toBe("ready");
    });
    await waitFor(() => {
      expect(week.count()).toBe(1);
    });

    const applied = await result.current.write.submit(TASK_ID);

    expect(applied).toBe(true);
    expect(complete.bodies).toEqual([null]);
    await waitFor(() => {
      expect(list.count()).toBe(2);
    });
    expect(week.count()).toBe(1);
  });
});
