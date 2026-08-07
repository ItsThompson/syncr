/* Reading the shell's push connection, and one type of event off it.
 *
 * `useServerEvents` is what a caller reaches for: it takes the handler and holds it in a ref, so a subscriber does
 * not re-subscribe on every render of the component that owns it. That guard belongs here rather than in each
 * consumer, because forgetting it costs a set insertion and a removal per keystroke the app draws for. */

import { useContext, useEffect, useRef } from "react";

import { EventStreamContext, type EventStream } from "./EventStreamProvider";
import type { ServerEvent } from "./frames";

export function useEventStream(): EventStream {
  return useContext(EventStreamContext);
}

/** Call `onEvent` for every event the stream delivers, for as long as the caller is mounted. */
export function useServerEvents(onEvent: (event: ServerEvent) => void): void {
  const stream = useEventStream();
  const latest = useRef(onEvent);

  useEffect(() => {
    latest.current = onEvent;
  });
  useEffect(
    () =>
      stream.subscribe((event) => {
        latest.current(event);
      }),
    [stream],
  );
}
