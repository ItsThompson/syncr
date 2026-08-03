/* It is coming, and here is what is being waited for.
 *
 * NO SPINNER, AND NOT BECAUSE ONE WAS FORGOTTEN. There is no spinner in this kit to reach for: motion is zero,
 * `--duration` is 0s, and the theme clears every animation namespace, so the usual spinner cannot be drawn in
 * this language at all. What replaces it is a sentence naming what is outstanding, which a spinner never said.
 *
 * It carries no action. Waiting is not a state a reader repairs, and offering a button here would invite a second
 * request for the thing already in flight. */

import { StatusSurface } from "./StatusSurface";

export interface PendingStateProps {
  /** What is being waited for: `Solving this week`, `Reading your calendars`. */
  readonly title: string;
  /** What is known meanwhile, such as which plan is still on screen. */
  readonly detail: string;
}

export function PendingState({ title, detail }: PendingStateProps) {
  return <StatusSurface kind="pending" title={title} detail={detail} />;
}
