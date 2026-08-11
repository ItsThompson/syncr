/* THE OPERATION LIFECYCLE: THE SEED, THE FOUR TERMINAL STATUSES, A SUPERSESSION CHAIN, AND THE FALLBACK.
 *
 * Every case here is driven through the shipped path. The events are real frames over a real stream, the polled
 * read goes through the real client to the real route the api declares, and the seed is the week view the screen
 * itself reads. The one thing a test supplies is which frames arrive and when.
 *
 * WHY THE PROVIDER'S PRESENCE IS PART OF EVERY CASE. Polling engages only while the push connection is not open, so
 * a test that mounted the hook without a stream would exercise the fallback while claiming to test push, and one
 * that mounted it with a stream would never reach the fallback at all. Each case says which it is. */

import { configure, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ReactNode } from "react";

import { apiServer } from "../../testing/apiServer";
import {
  countedHandler,
  eventStream,
  refusedEventStream,
  type EventStreamStub,
} from "../../testing/apiStub";
import { FreshCache } from "../../testing/renderRoute";
import {
  ISO_WEEK,
  OPERATION_ID,
  SUCCESSOR_ID,
  buildOperation,
  buildReadings,
  buildWeekView,
} from "../../routes/week/__tests__/fixtures";
import { EventStreamProvider } from "../events";
import { useOperation } from "./useOperation";
import type { WeekView } from "./useWeek";

/* THE WAITS ARE LONGER THAN THE DEFAULT SECOND, and deliberately. Every case here crosses a real chunked stream or
 * a real interval-driven read, and the suite runs 130 files in parallel: a second is a budget the machine sets
 * rather than the behaviour. What is being asserted is that something happens, not how fast.
 *
 * `SETTLE_MS` is the other half. Three cases assert that nothing FURTHER happens, which no condition can be waited
 * on: they let the interval and the invalidation both have their chance and then read the count. */
configure({ asyncUtilTimeout: 4000 });
const SETTLE_MS = 150;

const WEEK = `/api/v1/weeks/${ISO_WEEK}`;
const OPERATION = `/api/v1/operations/${OPERATION_ID}`;
const SUCCESSOR = `/api/v1/operations/${SUCCESSOR_ID}`;

/** The shell's own composition: the provider around whatever reads it. Reconnect fast, so a drop is observable. */
function withStream({ children }: { readonly children: ReactNode }) {
  return (
    <FreshCache>
      <EventStreamProvider reconnectMs={5}>{children}</EventStreamProvider>
    </FreshCache>
  );
}

function installWeek(view: WeekView) {
  const week = countedHandler(WEEK, { status: 200, body: view });
  apiServer.use(week.handler);
  return week;
}

function mount() {
  return renderHook(() => useOperation(ISO_WEEK), { wrapper: withStream });
}

/* Installed BEFORE the hook mounts, because the provider opens the connection on mount: a helper that waited for a
 * connection first would wait for one nothing had asked for. */
function installStream(): EventStreamStub {
  const stream = eventStream();
  apiServer.use(stream.handler);
  return stream;
}

/** Mounted, with the push connection open, which is the state every pushed case is about. */
async function mountConnected(stream: EventStreamStub) {
  const mounted = mount();
  await waitFor(() => expect(stream.connections()).toBe(1));
  return mounted;
}

describe("the seed", () => {
  it("takes the operation the week view carries, so a reload does not lose one in flight", async () => {
    installWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    const { result } = mount();

    await waitFor(() => expect(result.current.operation?.id).toBe(OPERATION_ID));
    expect(result.current.planCurrency).toBe("solving");
  });

  it("reads the server's own currency when nothing is in flight", async () => {
    installWeek(buildWeekView({ readings: buildReadings({ planCurrency: "stale" }) }));
    const { result } = mount();

    await waitFor(() => expect(result.current.planCurrency).toBe("stale"));
    expect(result.current.operation).toBeNull();
  });

  it("says solving from an operation the read that produced the readings could not have seen", async () => {
    installWeek(buildWeekView({ readings: buildReadings({ planCurrency: "current" }) }));
    const { result } = mount();
    await waitFor(() => expect(result.current.planCurrency).toBe("current"));

    result.current.track(buildOperation({ status: "pending" }));

    await waitFor(() => expect(result.current.planCurrency).toBe("solving"));
  });
});

describe("a terminal status arriving over the stream", () => {
  it("succeeded invalidates the week once, and once only", async () => {
    const week = installWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    const stream = installStream();
    const { result } = await mountConnected(stream);
    await waitFor(() => expect(result.current.operation?.id).toBe(OPERATION_ID));
    await waitFor(() => expect(week.count()).toBe(1));

    stream.push("operation", buildOperation({ status: "succeeded" }));

    await waitFor(() => expect(week.count()).toBe(2));
    /* ONE refetch and ONE redraw. A second invalidation would be a second read of a week nothing changed. */
    await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));
    expect(week.count()).toBe(2);
    expect(result.current.failure).toBeNull();
  });

  it("failed keeps the plan and states the api's own sentence", async () => {
    const week = installWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    const stream = installStream();
    const { result } = await mountConnected(stream);
    await waitFor(() => expect(week.count()).toBe(1));

    stream.push(
      "operation",
      buildOperation({
        status: "failed",
        statement: "This solve failed. The plan on screen is the last one that landed.",
        error: { code: "solver_timeout", message: "no plan within the budget" },
      }),
    );

    await waitFor(() => expect(result.current.failure?.code).toBe("solver_timeout"));
    expect(result.current.failure?.statement).toContain("the last one that landed");
    expect(result.current.planCurrency).toBe("stale");
    /* The plan of record did not change, so nothing is refetched: the week is read once, at mount. */
    expect(week.count()).toBe(1);
  });

  it("superseded is followed along the chain and never surfaces as a failure", async () => {
    const week = installWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    const stream = installStream();
    const { result } = await mountConnected(stream);
    await waitFor(() => expect(result.current.operation?.id).toBe(OPERATION_ID));

    stream.push("operation", buildOperation({ status: "superseded", supersededBy: SUCCESSOR_ID }));

    /* THE OBSERVABLE THAT ONLY FOLLOWING PRODUCES: the hook now holds an identifier it has no record for, so there
     * is no operation to render and it is still waiting. A hook that surfaced the supersession would be holding a
     * terminal record, which reads as the server's own `current`. Waiting on `planCurrency` would prove nothing
     * here, because the seed was already running and already said `solving`. */
    await waitFor(() => expect(result.current.operation).toBeNull());
    expect(result.current.planCurrency).toBe("solving");
    expect(result.current.failure).toBeNull();

    stream.push(
      "operation",
      buildOperation({ id: SUCCESSOR_ID, status: "succeeded", statement: "This week is current." }),
    );

    await waitFor(() => expect(week.count()).toBe(2));
    expect(result.current.operation?.id).toBe(SUCCESSOR_ID);
  });

  it("stops at a superseded operation that names no successor, rather than following nothing", async () => {
    /* The wire type permits it: the status word and the successor are two keys, and nothing in the generated type
     * ties them. So the reader needs an answer for the pair, and the answer is that there is nothing to follow, so
     * the record itself is the answer. */
    installWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    const stream = installStream();
    const { result } = await mountConnected(stream);
    await waitFor(() => expect(result.current.operation?.id).toBe(OPERATION_ID));

    stream.push("operation", buildOperation({ status: "superseded", supersededBy: null }));

    await waitFor(() => expect(result.current.operation?.status).toBe("superseded"));
    expect(result.current.planCurrency).toBe("current");
    expect(result.current.failure).toBeNull();
  });

  it("follows a chain two hops long, because a burst of edits produces one", async () => {
    installWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    const stream = installStream();
    const { result } = await mountConnected(stream);
    await waitFor(() => expect(result.current.operation?.id).toBe(OPERATION_ID));
    const third = "0f9b2c1e-0000-4000-8000-000000000003";

    stream.push("operation", buildOperation({ status: "superseded", supersededBy: SUCCESSOR_ID }));
    stream.push(
      "operation",
      buildOperation({ id: SUCCESSOR_ID, status: "superseded", supersededBy: third }),
    );

    /* Two hops in, the hook holds an identifier it has no record for and is still waiting. A hook that did not
     * follow would be holding a TERMINAL record here, so it would read the server's `current` and claim the plan
     * was up to date. */
    await waitFor(() => expect(result.current.operation).toBeNull());
    expect(result.current.planCurrency).toBe("solving");
    expect(result.current.failure).toBeNull();

    stream.push("operation", buildOperation({ id: third, status: "running" }));

    await waitFor(() => expect(result.current.operation?.id).toBe(third));
  });

  it("ignores an operation for another week, because two weeks are two plans", async () => {
    const week = installWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    const stream = installStream();
    const { result } = await mountConnected(stream);
    await waitFor(() => expect(week.count()).toBe(1));

    stream.push(
      "operation",
      buildOperation({
        id: "0f9b2c1e-0000-4000-8000-0000000000ff",
        status: "succeeded",
        target: { isoWeek: "2026-W08", sourceId: null },
      }),
    );

    await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));
    expect(week.count()).toBe(1);
    expect(result.current.operation?.id).toBe(OPERATION_ID);
  });
});

describe("the polling fallback", () => {
  it("does not engage while the push connection is open", async () => {
    installWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    const stream = installStream();
    const polled = countedHandler(OPERATION, { status: 200, body: buildOperation() });
    apiServer.use(polled.handler);

    const { result } = await mountConnected(stream);
    await waitFor(() => expect(result.current.operation?.id).toBe(OPERATION_ID));
    await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));

    expect(polled.count()).toBe(0);
  });

  it("engages while the stream is refused, and reads the operation by identifier", async () => {
    installWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    apiServer.use(refusedEventStream());
    const polled = countedHandler(OPERATION, {
      status: 200,
      body: buildOperation({ status: "running" }),
    });
    apiServer.use(polled.handler);

    mount();

    await waitFor(() => expect(polled.count()).toBeGreaterThan(0));
  });

  it("stops once the polled read reports a terminal status", async () => {
    const week = installWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    apiServer.use(refusedEventStream());
    const polled = countedHandler(OPERATION, {
      status: 200,
      body: buildOperation({ status: "succeeded" }),
    });
    apiServer.use(polled.handler);

    mount();

    await waitFor(() => expect(week.count()).toBe(2));
    const answered = polled.count();
    await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));
    expect(polled.count()).toBe(answered);
  });

  it("follows a supersession over the fallback too, so the two channels agree", async () => {
    installWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    apiServer.use(refusedEventStream());
    apiServer.use(
      countedHandler(OPERATION, {
        status: 200,
        body: buildOperation({ status: "superseded", supersededBy: SUCCESSOR_ID }),
      }).handler,
    );
    const successor = countedHandler(SUCCESSOR, {
      status: 200,
      body: buildOperation({ id: SUCCESSOR_ID, status: "running" }),
    });
    apiServer.use(successor.handler);

    const { result } = mount();

    await waitFor(() => expect(successor.count()).toBeGreaterThan(0));
    expect(result.current.operation?.id).toBe(SUCCESSOR_ID);
    expect(result.current.failure).toBeNull();
  });
});
