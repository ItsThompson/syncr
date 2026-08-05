/* THE WEEK WITH NO PLAN, WHICH IS TWO STATES AND NEVER A BLANK GRID.
 *
 * The two are the visible face of the planning horizon. A week beyond it has no plan BY DESIGN, because a read
 * never triggers work, so saying so with an action beats rendering an empty grid the reader cannot tell from a
 * failure.
 *
 * BOTH STATES ARE STATIC. Nothing here spins, and there is nothing in the kit it could spin with.
 *
 * THE SENTENCE IS THE SERVER'S. `statement` is composed where the horizon's own dates and the missing inputs are
 * in hand, so this screen and the horizon maintainer cannot word the same fact differently. What this component
 * decides is the TITLE and the ACTIONS, which are the screen's business rather than the payload's.
 *
 * A MISSING MINIMUM INPUT OUTRANKS THE HORIZON, and the payload has already applied that: a tenant with no Areas
 * cannot plan any week, so reporting a far week as beyond the horizon would offer two actions that both fail. The
 * ordering is not re-decided here. */

import type { ReactNode } from "react";

import { Button } from "../../primitives";
import { EmptyState } from "../status";

/** Why a week holds no plan. The wire's own two words, and the vocabulary is closed at them. */
export type EmptyWeekReason = "outside_horizon" | "setup_incomplete";

export interface EmptyWeekProps {
  readonly reason: EmptyWeekReason;
  /** The server's sentence: why this week holds no plan, and what still works. */
  readonly statement: string;
  /** Where the reader goes to declare what a plan needs. Rendered for the setup state only. */
  readonly setupHref: string;
  /** Where the reader goes to widen the projection horizon. Rendered for the horizon state only. */
  readonly extendHorizonHref: string;
  /** Asks for this week to be solved now. Rendered for the horizon state only. */
  readonly onSolveNow: () => void;
}

const TITLE: Readonly<Record<EmptyWeekReason, string>> = {
  outside_horizon: "This week is beyond your planning horizon",
  setup_incomplete: "This week cannot be planned yet",
};

export function EmptyWeek({
  reason,
  statement,
  setupHref,
  extendHorizonHref,
  onSolveNow,
}: EmptyWeekProps) {
  return <EmptyState action={actionsFor(reason)} detail={statement} title={TITLE[reason]} />;

  /* Two actions for the horizon and one for the setup state, because the horizon has two honest repairs and a
   * missing Area has exactly one. A reader is never asked to choose between two ways of fixing one thing.
   *
   * WIDENING THE HORIZON IS A DESTINATION AND SOLVING IS A REQUEST, so one is a real link and the other is a
   * button. A link keeps middle-click, cmd-click and the browser's own affordances; a button is what a write is. */
  function actionsFor(state: EmptyWeekReason): ReactNode {
    if (state === "setup_incomplete") {
      return (
        <Button asChild rank="primary">
          <a href={setupHref}>Finish setting up</a>
        </Button>
      );
    }
    return (
      <>
        <Button asChild rank="secondary">
          <a href={extendHorizonHref}>Extend the horizon</a>
        </Button>
        <Button onClick={onSolveNow} rank="primary">
          Solve this week now
        </Button>
      </>
    );
  }
}
