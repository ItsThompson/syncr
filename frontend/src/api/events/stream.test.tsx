/* THE PUSH CONNECTION, DRIVEN OVER A REAL STREAM.
 *
 * msw intercepts `fetch`, so what these tests exercise is the shipped reader: the real request, the real chunked
 * response, the real frame parser and the real reconnect. Nothing is stubbed between the frame and the subscriber,
 * which is the whole reason the connection is a `fetch` rather than an `EventSource` a jsdom test could only fake.
 *
 * THE FRAMES ARE THE API'S OWN, written by `eventStream()` in the api double exactly as
 * `syncr_api.events.envelopes.as_frame` writes them. */

import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import { eventStream } from "../../testing/apiStub";
import { buildOperation } from "../../routes/week/__tests__/fixtures";
import { EventStreamProvider } from "./EventStreamProvider";
import { useEventStream, useServerEvents } from "./useEventStream";
import type { ServerEvent } from "./frames";

/* The shape's own factory, so this frame carries every key the api sends rather than the six a reader here
 * happens to assert on. */
const OPERATION = buildOperation({ status: "running", statement: "A solve is running." });

function Reader({ seen }: { readonly seen: ServerEvent[] }) {
  const { isConnected } = useEventStream();
  useServerEvents((event) => seen.push(event));

  return <p>{isConnected ? "connected" : "not connected"}</p>;
}

function renderStream(seen: ServerEvent[], reconnectMs?: number) {
  return render(
    <EventStreamProvider reconnectMs={reconnectMs}>
      <Reader seen={seen} />
    </EventStreamProvider>,
  );
}

describe("the push connection", () => {
  it("opens one connection and reports it", async () => {
    const stream = eventStream();
    apiServer.use(stream.handler);
    const seen: ServerEvent[] = [];

    renderStream(seen);

    expect(await screen.findByText("connected")).toBeInTheDocument();
    expect(stream.connections()).toBe(1);
  });

  it("delivers an event to a subscriber, narrowed to its own type", async () => {
    const stream = eventStream();
    apiServer.use(stream.handler);
    const seen: ServerEvent[] = [];
    renderStream(seen);
    await screen.findByText("connected");

    stream.push("operation", OPERATION);

    await waitFor(() => expect(seen).toHaveLength(1));
    const event = seen[0];
    expect(event.type).toBe("operation");
    if (event.type !== "operation") throw new Error("narrowing failed");
    expect(event.data.target.isoWeek).toBe("2026-W07");
  });

  it("delivers nothing for a heartbeat, so an idle stream wakes no subscriber", async () => {
    const stream = eventStream();
    apiServer.use(stream.handler);
    const seen: ServerEvent[] = [];
    renderStream(seen);

    await screen.findByText("connected");

    expect(seen).toEqual([]);
  });

  it("reports the drop and reconnects, so a blip is not a stuck interface", async () => {
    const stream = eventStream();
    apiServer.use(stream.handler);
    const seen: ServerEvent[] = [];
    renderStream(seen, 1);
    await screen.findByText("connected");

    stream.drop();

    /* Reconnected, and pushing again reaches the subscriber over the SECOND connection: a reader that reported
     * being connected while holding a finished stream would pass the count assertion and drop every event. */
    await waitFor(() => expect(stream.connections()).toBe(2));
    expect(await screen.findByText("connected")).toBeInTheDocument();
    stream.push("operation", OPERATION);
    await waitFor(() => expect(seen).toHaveLength(1));
  });

  it("reports not connected while the api refuses the stream", async () => {
    const seen: ServerEvent[] = [];
    apiServer.use(
      http.get(`${window.location.origin}/api/v1/events`, () =>
        HttpResponse.json({ title: "Service unavailable" }, { status: 503 }),
      ),
    );

    renderStream(seen, 50);

    expect(await screen.findByText("not connected")).toBeInTheDocument();
  });
});
