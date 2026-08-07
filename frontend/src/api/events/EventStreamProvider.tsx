/* THE ONE PUSH CONNECTION, OWNED BY THE SHELL AND READ BY WHATEVER CARES.
 *
 * ONE CONNECTION FOR THE WHOLE APPLICATION. The stream carries every operation, conflict, projection and notice of
 * an account, so a second connection would be a second copy of the same fan-out and a second thing to reconnect.
 * The shell is where it belongs for the same reason the keyboard map is: a route comes and goes and the connection
 * must not.
 *
 * SUBSCRIBERS ARE HELD IN A REF AND THE VALUE THE CONTEXT CARRIES IS STABLE, so a subscriber arriving does not
 * reopen the connection. Only `isConnected` changes, and it changes because the connection did.
 *
 * WITH NO PROVIDER MOUNTED THERE IS NO PUSH, and that is a real state rather than a misconfiguration: a hook reads
 * `isConnected: false` and falls back to polling, which is exactly what it does when the connection drops. A
 * throwing default would make a component untestable outside the shell for no gain. */

import { createContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { readEventStream } from "./stream";
import type { ServerEvent } from "./frames";

export interface EventStream {
  /** True while the push connection is open. Polling is the fallback for exactly when it is not. */
  readonly isConnected: boolean;
  /** Register a handler for every event, filtered by the subscriber. Returns the unsubscribe. */
  readonly subscribe: (handler: (event: ServerEvent) => void) => () => void;
}

const NO_PUSH: EventStream = { isConnected: false, subscribe: () => () => undefined };

export const EventStreamContext = createContext<EventStream>(NO_PUSH);

export interface EventStreamProviderProps {
  readonly children: ReactNode;
  /**
   * How long a dropped connection waits before trying again.
   *
   * A parameter because the wait is the one thing about this module that a test cannot wait out: production takes
   * the default, and a test that drives a reconnect passes a shorter one.
   */
  readonly reconnectMs?: number | undefined;
}

export function EventStreamProvider({ children, reconnectMs }: EventStreamProviderProps) {
  const [isConnected, setIsConnected] = useState(false);
  const subscribers = useRef(new Set<(event: ServerEvent) => void>());

  useEffect(() => {
    const controller = new AbortController();
    void readEventStream({
      signal: controller.signal,
      reconnectMs,
      onConnected: setIsConnected,
      onEvent: (event) => {
        for (const subscriber of subscribers.current) subscriber(event);
      },
    });
    return () => controller.abort();
  }, [reconnectMs]);

  const stream = useMemo<EventStream>(
    () => ({
      isConnected,
      subscribe: (handler) => {
        subscribers.current.add(handler);
        return () => subscribers.current.delete(handler);
      },
    }),
    [isConnected],
  );

  return <EventStreamContext.Provider value={stream}>{children}</EventStreamContext.Provider>;
}
