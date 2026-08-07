/* THE PUSH CONNECTION: ONE READER OVER `GET /api/v1/events`, AND THE RECONNECT THAT FOLLOWS A DROP.
 *
 * WHY `fetch` AND NOT `EventSource`. Three reasons, in the order they matter. The reconnect has to be observable,
 * because polling is engaged only while the push connection is down and returns to push on reconnect:
 * `EventSource` reconnects on its own schedule and reports `readyState`, so the fallback would be driven by a state
 * this application does not control. It is testable: msw intercepts `fetch`, so a test drives the REAL frame parser
 * over a real chunked response, where an `EventSource` test would drive a stub of a class jsdom does not implement
 * at all. And the session cookie rides on `credentials: include`, which is the same policy the one HTTP client
 * sets, rather than on a second spelling of it.
 *
 * A DROP IS EXPECTED, NOT AN ERROR. A proxy closing an idle connection is what the api's heartbeat exists to make
 * visible, so the loop reconnects after a fixed wait and reports being disconnected in between. Nothing here
 * surfaces a notice: a network blip is not something to tell the reader about, and the fallback is what keeps the
 * interface unstuck.
 *
 * THE WAIT IS FIXED RATHER THAN BACKED OFF. An api that is down is answered by the polling fallback, which is
 * already interval-driven, so escalating the wait here would only delay the return to push.
 *
 * SEQUENTIAL AWAITS ARE THE PROTOCOL. `no-await-in-loop` advises collecting promises and running them in parallel,
 * which is the opposite of what a stream is: the next chunk does not exist until the previous one has been read,
 * and the next connection must not be opened until this one has ended. Both loops are disabled by name with that
 * reason rather than restructured into a shape the rule likes and the transport does not. */

import { parseFrames, type ServerEvent } from "./frames";

export const EVENTS_PATH = "/api/v1/events";

/** How long a dropped connection waits before it tries again. */
export const RECONNECT_MS = 3000;

export interface StreamOptions {
  readonly onEvent: (event: ServerEvent) => void;
  /** Called with true when a connection is open and false the moment it is not. */
  readonly onConnected: (isConnected: boolean) => void;
  readonly signal: AbortSignal;
  readonly reconnectMs?: number | undefined;
}

/**
 * Read the stream until the signal aborts, reconnecting after each drop.
 *
 * Resolves only when aborted, so a caller awaits it to know the connection is finished with.
 */
export async function readEventStream(options: StreamOptions): Promise<void> {
  while (!options.signal.aborted) {
    // oxlint-disable-next-line no-await-in-loop -- one connection at a time: the next must not open until this one has ended
    await connectOnce(options);
  }
}

/** One connection, from open to closed, followed by the wait before another is tried. */
async function connectOnce(options: StreamOptions): Promise<void> {
  const { signal, onConnected, reconnectMs = RECONNECT_MS } = options;
  try {
    await readOnce(options);
  } catch {
    /* Every failure is the same failure: the connection is not open. Which of the transport's reasons it was
     * changes nothing a reader can act on, and the fallback is what covers the gap. */
  }
  onConnected(false);
  if (signal.aborted) return;
  await wait(reconnectMs, signal);
}

async function readOnce({ signal, onEvent, onConnected }: StreamOptions): Promise<void> {
  const response = await fetch(`${window.location.origin}${EVENTS_PATH}`, {
    credentials: "include",
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!response.ok || response.body === null) throw new Error(`events: ${String(response.status)}`);

  onConnected(true);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (!signal.aborted) {
    // oxlint-disable-next-line no-await-in-loop -- the next chunk does not exist until this one has been read
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseFrames(buffer);
    buffer = parsed.rest;
    for (const event of parsed.events) onEvent(event);
  }
  await reader.cancel();
}

/** A wait that ends early when the signal aborts, so unmounting does not hold a timer open. */
function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = (): void => {
      clearTimeout(timer);
      resolve();
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}
