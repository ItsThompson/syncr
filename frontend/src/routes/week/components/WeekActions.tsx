/* THE WEEK SCREEN'S BAND: the counts, the zoom reading, the session's entry, `Re-solve` and `Approve`.
 *
 * `Run the weekly session` IS A REAL LINK, not a button that assigns a location, which is what keeps middle-click and
 * cmd-click working and what makes the mode something a reader can send to themselves. It mirrors the closest existing
 * sibling exactly: the pie review is the same shape, a mode of a screen reachable by URL, and `AreaBand` carries its
 * `Run the pie review` link. A mode with no control in the product is a mode only a URL can open, which is not what
 * "triggered manually" means.
 *
 * IT IS ABSENT INSIDE THE SESSION, and `sessionHref` is `null` rather than optional so both call sites state which they
 * are. An optional prop would let a third caller be neither on purpose nor by accident.
 *
 * `Re-solve` DISPATCHES IMMEDIATELY, bypassing the debounce, and it is available whether or not a solve is already
 * pending: a reader who wants the plan now should never have to wait out a window they cannot see. The staleness rules
 * are the same as for any other trigger, so a solve already running is superseded by this one rather than blocked.
 *
 * `Approve` IS NEVER DISABLED BY AN INFEASIBILITY. syncr informs; it does not govern. The one thing that disables it is
 * having nothing to approve, which is a fact about the pending slot rather than a judgement about the week.
 *
 * THE PLAN CURRENCY IS NOT STATED HERE. It rides in the summary strip's `SCHEDULED` sub-line, BECAUSE it qualifies the
 * block count, and a band that repeated the word would be the second surface the rule exists to prevent. The count
 * here is the same figure the strip's cell reads, which is why the two cannot disagree about it.
 *
 * THE ZOOM READING IS THE GRID'S OWN ANSWER, not the level the screen asked for. The offerable range is clamped per
 * display, from a measurement only the grid has, so a band that rendered the setting would read `20h visible` over a
 * grid drawing 16 whenever the reader's level is past their display's cap. There is no figure to render before the grid
 * has reported one, which is what `null` states: a band with no grid beside it states no level rather than a guess.
 *
 * THE UNCONFIRMED DAYS ARE SERVED, NOT COUNTED HERE. The api decides which of a week's days have ended, hold a block
 * and are still unanswered, and the Today band reads the same rule's answer for its own window; counting the columns
 * this band sits above would be a second rule, and the payload carries no per-day confirmation for it to count. */

import { Link } from "react-router";

import { KeyHint } from "../../../ui/domain";
import { Button } from "../../../ui/primitives";

export interface WeekActionsProps {
  readonly blockCount: number;
  /** Days of THIS week that have ended, hold a block and are unconfirmed, as the week read served it. */
  readonly unconfirmedDays: number;
  /** The visible hours the grid reported it is drawing, or null before it has measured. */
  readonly drawnHours: number | null;
  readonly hasProposal: boolean;
  /** Where the weekly session opens for this week, or null when this band IS the session. */
  readonly sessionHref: string | null;
  readonly onResolveNow: () => void;
  readonly onApprove: () => void;
}

function unconfirmedReading(unconfirmedDays: number): string {
  return `${unconfirmedDays} ${unconfirmedDays === 1 ? "day" : "days"} unconfirmed`;
}

export function WeekActions({
  blockCount,
  unconfirmedDays,
  drawnHours,
  hasProposal,
  sessionHref,
  onResolveNow,
  onApprove,
}: WeekActionsProps) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <p className="text-eyebrow text-text-muted">
        {blockCount} blocks · {unconfirmedReading(unconfirmedDays)}
        {drawnHours === null ? null : (
          <>
            {" · "}
            {drawnHours}h visible <KeyHint keys="z" />
          </>
        )}
      </p>
      {sessionHref === null ? null : (
        <Link className="text-sm underline" to={sessionHref}>
          Run the weekly session
        </Link>
      )}
      <Button onClick={onResolveNow} rank="secondary" size="sm">
        Re-solve
      </Button>
      <Button isDisabled={!hasProposal} onClick={onApprove} rank="primary" size="sm">
        Approve <KeyHint keys="Shift+A" />
      </Button>
    </div>
  );
}
