/* There is nothing here yet, and what to do about it.
 *
 * STATIC, like the other two. The Week screen's empty states are the visible face of the planning horizon: a
 * week beyond it has no plan by design, because a read never triggers work, and saying so with an action beats
 * rendering a blank grid.
 *
 * The plate and the action are the caller's own nodes. Which instrument a screen shows and whether its repair is
 * a link or a mutation are decisions this surface has no business making. */

import type { ReactNode } from "react";

import { StatusSurface } from "./StatusSurface";

export interface EmptyStateProps {
  /** What is not here, in the reader's words. */
  readonly title: string;
  /** Why it is not here, and what that means for the plan. */
  readonly detail: string;
  /** The repair: `<Button asChild><Link to=...>` for a step, or a button for a solve. */
  readonly action?: ReactNode;
  /** A `Plate`. Empty states are one of the five surfaces illustration is sanctioned on. */
  readonly plate?: ReactNode;
}

export function EmptyState({ title, detail, action, plate }: EmptyStateProps) {
  return <StatusSurface kind="empty" title={title} detail={detail} action={action} plate={plate} />;
}
