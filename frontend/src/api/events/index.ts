/* THE EVENT STREAM: the one push connection, the frames it carries, and the four types they name.
 *
 * A hook reads the connection through `useEventStream` or `useServerEvents`, and nothing outside this directory
 * knows the connection is a `fetch` rather than an `EventSource`. `stream.ts` states why it is.
 */

export {
  EventStreamContext,
  EventStreamProvider,
  type EventStream,
  type EventStreamProviderProps,
} from "./EventStreamProvider";
export {
  EVENT_TYPES,
  eventOfFrame,
  isTerminal,
  parseFrames,
  type Conflict,
  type EventType,
  type Operation,
  type OperationStatus,
  type ParsedFrames,
  type ProjectionPass,
  type ServerEvent,
} from "./frames";
export { EVENTS_PATH, RECONNECT_MS, readEventStream, type StreamOptions } from "./stream";
export { useEventStream, useServerEvents } from "./useEventStream";
