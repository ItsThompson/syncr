/* It did not arrive, and here is what is still true.
 *
 * A failure surface, and still static: nothing spins while a request is retried. It takes the oxide TEXT step for
 * its title rather than the marker step, because a title is words and the two steps are not interchangeable; the
 * mark beside it takes the marker step, where 3:1 is the bar.
 *
 * It is `role="alert"`, which is the one surface in this family that interrupts a screen reader. */

import type { ReactNode } from "react";

import { StatusSurface } from "./StatusSurface";

export interface ErrorStateProps {
  /** What failed, in the reader's words rather than the transport's. */
  readonly title: string;
  /** What is still true: which plan is on screen, and what remains available. */
  readonly detail: string;
  /** The repair, as the caller's own control. */
  readonly action?: ReactNode;
  /** A `Plate`. An error screen is one of the five surfaces illustration is sanctioned on. */
  readonly plate?: ReactNode;
}

export function ErrorState({ title, detail, action, plate }: ErrorStateProps) {
  return <StatusSurface kind="error" title={title} detail={detail} action={action} plate={plate} />;
}
