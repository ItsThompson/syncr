/* WHAT ONE SERVER-SENT FRAME HOLDS, AND WHICH OF THE FOUR TYPES IT IS.
 *
 * The api's own vocabulary, mirrored: `syncr_api.events.config` declares exactly four event types and every one of
 * them states WHAT changed rather than carrying the change. A payload holding a plan document is refused where it
 * is published, so nothing here has to be prepared to receive one.
 *
 * THE DATA IS THE WIRE MODEL THE ROUTE ALREADY ANSWERS WITH, aliased identically: `syncr_api.events.envelopes`
 * dumps `OperationResponse`, `ConflictResponse` and the notice through the same serialisation their HTTP responses
 * use. So the types below are read out of the generated schema rather than written a second time, which is what
 * makes "no document reaches the stream" a property of those schemas instead of a claim this file restates.
 *
 * A PROJECTION'S PAYLOAD IS THE ONE SHAPE THE DOCUMENT DOES NOT DESCRIBE. It is composed in the envelope builder
 * rather than dumped from a response model, so no generated type covers it, and it is declared here with that
 * stated: the reader that narrows it is the only place a hand-written stream type exists. */

import type { components } from "../schema";
import type { WireNotice } from "../../ui/domain";

export type Operation = components["schemas"]["OperationResponse"];
export type OperationStatus = components["schemas"]["OperationStatus"];
export type Conflict = components["schemas"]["ConflictResponse"];

/** What one reconciliation pass did, which is the whole pass rather than this week's share of it. */
export interface ProjectionPass {
  readonly isoWeek: string;
  readonly pass: {
    readonly inserted: number;
    readonly patched: number;
    readonly deleted: number;
    readonly foreignDeleted: number;
    readonly unchanged: number;
    readonly durationMs: number;
  };
}

/** One thing that changed, as the stream names it. */
export type ServerEvent =
  | { readonly type: "operation"; readonly data: Operation }
  | { readonly type: "conflict"; readonly data: Conflict }
  | { readonly type: "projection"; readonly data: ProjectionPass }
  | { readonly type: "notice"; readonly data: WireNotice };

export type EventType = ServerEvent["type"];

/**
 * Every type the stream declares, which is the api's own set.
 *
 * Exported because it is what a sweep over the union has to iterate: a test that named the four itself would
 * keep passing the day a fifth is added, and the question worth asking of this union -- which of these
 * interrupts the reader -- has to be asked of every member.
 */
export const EVENT_TYPES: readonly EventType[] = ["operation", "conflict", "projection", "notice"];

/** True for a status no further event can follow, which is what ends a subscription's interest. */
export function isTerminal(status: OperationStatus): boolean {
  return status === "succeeded" || status === "failed" || status === "superseded";
}

/**
 * The event a raw frame names, or null.
 *
 * Null covers three cases that are all "nothing to hand a subscriber" rather than three errors: a heartbeat, which
 * is a comment and carries no type at all; a type this client does not know, which is how a server that gained a
 * fifth one stays compatible; and a data line that is not JSON, which cannot be narrowed any further here.
 */
export function eventOfFrame(frame: string): ServerEvent | null {
  let type: string | null = null;
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) type = line.slice("event:".length).trim();
    if (line.startsWith("data:")) data.push(line.slice("data:".length).trim());
  }
  if (type === null || data.length === 0) return null;
  if (!EVENT_TYPES.some((known) => known === type)) return null;
  try {
    /* The narrowing the wire cannot do for us. The four types and their four payloads are one pairing in the
     * envelope builder, so a type this client knows arrives with the payload that type names. */
    return { type, data: JSON.parse(data.join("\n")) } as ServerEvent;
  } catch {
    return null;
  }
}

export interface ParsedFrames {
  readonly events: readonly ServerEvent[];
  /** The tail that has not been terminated by a blank line yet, which the next chunk continues. */
  readonly rest: string;
}

/**
 * Every complete frame in a buffer, and what is left over.
 *
 * A CHUNK IS NOT A FRAME. A stream splits wherever the transport decided to, so a frame can arrive in two reads
 * and two frames can arrive in one. Carrying the remainder forward is what makes the reader independent of where
 * the split fell, which is the one property a test over a hand-chunked stream can actually pin.
 */
export function parseFrames(buffer: string): ParsedFrames {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  const events: ServerEvent[] = [];
  for (const part of parts) {
    const event = eventOfFrame(part);
    if (event !== null) events.push(event);
  }
  return { events, rest };
}
