/* THE FRAME PARSER, WHICH IS WHERE THE WIRE FORMAT IS ACTUALLY UNDERSTOOD.
 *
 * A CHUNK IS NOT A FRAME, and that is the property worth pinning: the transport splits wherever it likes, so every
 * case here is really "does the reader depend on where the split fell". The frames are the api's own, from
 * `syncr_api.events.envelopes.as_frame`: a named type, one compact `data:` line, and a blank line. */

import { describe, expect, it } from "vitest";

import { buildOperation } from "../../routes/week/__tests__/fixtures";
import { eventOfFrame, isTerminal, parseFrames } from "./frames";

const HEARTBEAT = ": heartbeat\n\n";

function frame(type: string, data: unknown): string {
  return `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
}

/* Built by the shape's own factory rather than spelled here, so a key added to the wire arrives in this frame
 * instead of leaving it a smaller operation than any the api sends. */
const OPERATION = buildOperation({
  status: "succeeded",
  statement: "This week's plan is current.",
});

describe("eventOfFrame", () => {
  it("reads the type and the payload of a real frame", () => {
    expect(eventOfFrame(frame("operation", OPERATION).trimEnd())).toEqual({
      type: "operation",
      data: OPERATION,
    });
  });

  it("answers null for a heartbeat, which is a comment and not an event", () => {
    expect(eventOfFrame(HEARTBEAT.trimEnd())).toBeNull();
  });

  it("answers null for a type this client does not know, so a fifth type is not a crash", () => {
    expect(eventOfFrame("event: promotion\ndata: {}")).toBeNull();
  });

  it("answers null for a data line that is not JSON", () => {
    expect(eventOfFrame("event: notice\ndata: <html>gateway timeout</html>")).toBeNull();
  });

  it("answers null for a frame with a type and no data", () => {
    expect(eventOfFrame("event: operation")).toBeNull();
  });
});

describe("parseFrames", () => {
  it("reads two frames out of one chunk", () => {
    const parsed = parseFrames(
      frame("operation", OPERATION) + frame("projection", { isoWeek: "x" }),
    );

    expect(parsed.events.map((event) => event.type)).toEqual(["operation", "projection"]);
    expect(parsed.rest).toBe("");
  });

  it("holds a half-arrived frame back until the rest of it lands", () => {
    const whole = frame("operation", OPERATION);
    const split = whole.length - 12;

    const first = parseFrames(whole.slice(0, split));
    expect(first.events).toEqual([]);

    const second = parseFrames(first.rest + whole.slice(split));
    expect(second.events).toEqual([{ type: "operation", data: OPERATION }]);
    expect(second.rest).toBe("");
  });

  it("drops a heartbeat between two frames without disturbing either", () => {
    const parsed = parseFrames(
      frame("operation", OPERATION) + HEARTBEAT + frame("conflict", { id: "c" }),
    );

    expect(parsed.events.map((event) => event.type)).toEqual(["operation", "conflict"]);
  });
});

describe("isTerminal", () => {
  it.each(["succeeded", "failed", "superseded"] as const)("%s is terminal", (status) => {
    expect(isTerminal(status)).toBe(true);
  });

  it.each(["pending", "running"] as const)("%s is not", (status) => {
    expect(isTerminal(status)).toBe(false);
  });
});
