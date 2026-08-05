/* The three writes on a day: what each SENDS, what each INVALIDATES, and what the reader sees before the
 * response lands.
 *
 * A network test is the only thing that can say those. The recording body carries the week the ledger's
 * date belongs to, which no component test would notice was missing, and the optimistic frame is a state
 * the cache holds for one round trip: asserting it needs a response the test controls the timing of.
 *
 * The reads are exercised through the screen. What is here is the write half. */

import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import { countedHandler, recordingHandler } from "../../testing/apiStub";
import { FreshCache } from "../../testing/renderRoute";
import {
  BLOCK_GYM,
  DATE,
  ISO_WEEK,
  buildBackfill,
  buildDay,
  buildOutcomeRejection,
  buildRow,
} from "../../routes/today/__tests__/fixtures";
import { heldResponse } from "../../routes/today/__tests__/render";
import { stateOf } from "./dayProjection";
import { useBackfill, useDay, useDayConfirmation, useOutcomeRecording } from "./useDay";

const DAY = `/api/v1/days/${DATE}`;
const OUTCOME = `/api/v1/blocks/${BLOCK_GYM}/outcome`;
const CONFIRM = `${DAY}/confirm`;
const RANGE = "/api/v1/days/confirm-range";

const SKIP = { blockId: BLOCK_GYM, outcome: { isoWeek: ISO_WEEK, state: "skipped" } } as const;

describe("useOutcomeRecording", () => {
  it("sends the state, the week the date belongs to, and nothing else", async () => {
    const write = recordingHandler("put", OUTCOME, { status: 200, body: null });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useOutcomeRecording(DATE, buildDay()), {
      wrapper: FreshCache,
    });
    await expect(result.current.record(SKIP)).resolves.toBe(true);

    expect(write.bodies).toEqual([{ isoWeek: ISO_WEEK, state: "skipped" }]);
  });

  it("invalidates the day it changed, and nothing else", async () => {
    const day = countedHandler(DAY, { status: 200, body: buildDay() });
    apiServer.use(
      day.handler,
      recordingHandler("put", OUTCOME, { status: 200, body: null }).handler,
    );

    const { result } = renderHook(
      () => ({ day: useDay(DATE), write: useOutcomeRecording(DATE, buildDay()) }),
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.day.status).toBe("ready"));
    expect(day.count()).toBe(1);

    await result.current.write.record(SKIP);

    await waitFor(() => expect(day.count()).toBe(2));
  });

  /* The optimistic frame: the row reads as skipped while the request is still in flight, which is what
     makes the ledger answer in one action rather than in one round trip. */
  it("shows the row's new state before the api answers", async () => {
    const { held, release } = heldResponse();
    apiServer.use(
      http.get(`${window.location.origin}${DAY}`, () => HttpResponse.json(buildDay())),
      http.put(`${window.location.origin}${OUTCOME}`, async () => {
        await held;
        return HttpResponse.json(null);
      }),
    );

    const { result } = renderHook(
      () => {
        const day = useDay(DATE);
        return { day, write: useOutcomeRecording(DATE, day.status === "ready" ? day.data : null) };
      },
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.day.status).toBe("ready"));

    const recording = result.current.write.record(SKIP);
    await waitFor(() => {
      const day = result.current.day;
      expect(day.status === "ready" ? stateOf(day.data.behind[1]) : null).toBe("skipped");
    });

    release();
    await expect(recording).resolves.toBe(true);
  });

  /* The revert, and it is the day the row was rendered from rather than a refetch: an api that refused
     the write is an api a second request may not reach either. */
  it("puts the day back and names the row when the write is refused", async () => {
    apiServer.use(
      http.get(`${window.location.origin}${DAY}`, () => HttpResponse.json(buildDay())),
      http.put(`${window.location.origin}${OUTCOME}`, () =>
        HttpResponse.json(buildOutcomeRejection(), { status: 422 }),
      ),
    );

    const { result } = renderHook(
      () => {
        const day = useDay(DATE);
        return { day, write: useOutcomeRecording(DATE, day.status === "ready" ? day.data : null) };
      },
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.day.status).toBe("ready"));

    await expect(result.current.write.record(SKIP)).resolves.toBe(false);

    await waitFor(() => expect(result.current.write.refusal?.blockId).toBe(BLOCK_GYM));
    expect(result.current.write.refusal?.problem.status).toBe(422);
    const day = result.current.day;
    expect(day.status === "ready" ? stateOf(day.data.behind[1]) : null).toBe("presumed");
  });

  it("sends nothing but the day's own path when there is no day to project onto", async () => {
    const write = recordingHandler("put", OUTCOME, { status: 200, body: null });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useOutcomeRecording(DATE, null), { wrapper: FreshCache });
    await expect(result.current.record(SKIP)).resolves.toBe(true);

    expect(write.bodies).toHaveLength(1);
  });
});

describe("useDayConfirmation", () => {
  it("posts to the day's confirm path, carrying no body of its own", async () => {
    let sent: string | null = null;
    apiServer.use(
      http.post(`${window.location.origin}${CONFIRM}`, async ({ request }) => {
        sent = await request.text();
        return HttpResponse.json(buildDay());
      }),
    );

    const { result } = renderHook(() => useDayConfirmation(DATE, buildDay()), {
      wrapper: FreshCache,
    });
    await expect(result.current.submit()).resolves.toBe(true);

    expect(sent).toBe("");
  });

  it("settles every row before the api answers, and invalidates the day afterwards", async () => {
    const { held, release } = heldResponse();
    const day = countedHandler(DAY, { status: 200, body: buildDay() });
    apiServer.use(
      day.handler,
      http.post(`${window.location.origin}${CONFIRM}`, async () => {
        await held;
        return HttpResponse.json(buildDay());
      }),
    );

    const { result } = renderHook(
      () => {
        const read = useDay(DATE);
        return {
          read,
          write: useDayConfirmation(DATE, read.status === "ready" ? read.data : null),
        };
      },
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.read.status).toBe("ready"));

    const confirming = result.current.write.submit();
    await waitFor(() => {
      const read = result.current.read;
      expect(read.status === "ready" ? read.data.confirmedAt : null).not.toBeNull();
    });

    release();
    await expect(confirming).resolves.toBe(true);
    await waitFor(() => expect(day.count()).toBe(2));
  });

  it("puts the unconfirmed day back when the confirmation is refused", async () => {
    apiServer.use(
      http.get(`${window.location.origin}${DAY}`, () => HttpResponse.json(buildDay())),
      http.post(`${window.location.origin}${CONFIRM}`, () =>
        HttpResponse.json(buildOutcomeRejection({ detail: "That day has not begun yet." }), {
          status: 422,
        }),
      ),
    );

    const { result } = renderHook(
      () => {
        const read = useDay(DATE);
        return {
          read,
          write: useDayConfirmation(DATE, read.status === "ready" ? read.data : null),
        };
      },
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.read.status).toBe("ready"));

    await expect(result.current.write.submit()).resolves.toBe(false);

    const read = result.current.read;
    expect(read.status === "ready" ? read.data.confirmedAt : "not read").toBeNull();
    await waitFor(() => expect(result.current.write.problem?.status).toBe(422));
  });
});

describe("useBackfill", () => {
  it("sends the range it was given, both dates included", async () => {
    const write = recordingHandler("post", RANGE, { status: 200, body: buildBackfill() });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useBackfill(DATE), { wrapper: FreshCache });
    await expect(result.current.submit({ from: "2026-01-12", to: "2026-02-08" })).resolves.toBe(
      true,
    );

    expect(write.bodies).toEqual([{ from: "2026-01-12", to: "2026-02-08" }]);
  });

  /* What it settled comes from the response and not from the count the last read reported: the client
     holds a figure, and only the server knows which dates that figure came from. */
  it("keeps the figures the api answered with", async () => {
    apiServer.use(
      recordingHandler("post", RANGE, {
        status: 200,
        body: buildBackfill({ confirmedDays: 2, blocksRecorded: 19, unconfirmedDays: 1 }),
      }).handler,
    );

    const { result } = renderHook(() => useBackfill(DATE), { wrapper: FreshCache });
    await result.current.submit({ from: "2026-01-12", to: "2026-02-08" });

    await waitFor(() =>
      expect(result.current.settled).toEqual({
        confirmedDays: 2,
        blocksRecorded: 19,
        unconfirmedDays: 1,
      }),
    );
  });

  it("invalidates the day on screen, because its count of unconfirmed days has changed", async () => {
    const day = countedHandler(DAY, {
      status: 200,
      body: buildDay({ behind: [buildRow()], ahead: [], blockCount: 1, presumedCount: 1 }),
    });
    apiServer.use(
      day.handler,
      recordingHandler("post", RANGE, { status: 200, body: buildBackfill() }).handler,
    );

    const { result } = renderHook(() => ({ read: useDay(DATE), write: useBackfill(DATE) }), {
      wrapper: FreshCache,
    });
    await waitFor(() => expect(result.current.read.status).toBe("ready"));
    expect(day.count()).toBe(1);

    await result.current.write.submit({ from: "2026-01-12", to: "2026-02-08" });

    await waitFor(() => expect(day.count()).toBe(2));
  });

  it("keeps the refusal and settles nothing when the range is refused", async () => {
    apiServer.use(
      recordingHandler("post", RANGE, {
        status: 422,
        body: buildOutcomeRejection({ detail: "A backfill may cover at most 28 days." }),
      }).handler,
    );

    const { result } = renderHook(() => useBackfill(DATE), { wrapper: FreshCache });
    await expect(result.current.submit({ from: "2025-01-01", to: "2026-02-08" })).resolves.toBe(
      false,
    );

    await waitFor(() => expect(result.current.problem?.status).toBe(422));
    expect(result.current.settled).toBeNull();
  });
});
