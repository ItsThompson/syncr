/* THE WEEK SCREEN'S BAND: the counts, the zoom segment, the session's entry, `Re-solve` and `Approve`.
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
 * THE ZOOM SEGMENT IS THE GRID'S OWN ANSWER, NOT THE LEVEL THE SCREEN ASKED FOR. The offerable range is clamped per
 * display, from a measurement only the grid has, so a band that offered its own range would sell levels the reader's
 * display refuses and press a level the grid is not drawing. The segment renders the report's range whole, presses
 * the drawn level, and sends a pick to the same durable preference `z` updates. There is no answer before the grid has measured,
 * which is what `null` states: a band with no grid beside it offers no range rather than a guess.
 *
 * THE KEYSTROKE IS ADVERTISED BESIDE THE CONTROL, not inside it: the hint sits in ink beside segments whose own fill
 * is none, which is the pattern the day band and the backlog band set.
 *
 * THE UNCONFIRMED DAYS ARE SERVED, NOT COUNTED HERE. The api decides which of a week's days have ended, hold a block
 * and are still unanswered, and the Today band reads the same rule's answer for its own window; counting the columns
 * this band sits above would be a second rule, and the payload carries no per-day confirmation for it to count. */

import { Link } from "react-router";

import { KeyHint } from "../../../ui/domain";
import type { ZoomLevel } from "../../../ui/domain";
import { Button } from "../../../ui/primitives";
import { ZoomSegment } from "./ZoomSegment";

export interface WeekActionsProps {
  readonly blockCount: number;
  /** Days of THIS week that have ended, hold a block and are unconfirmed, as the week read served it. */
  readonly unconfirmedDays: number;
  /** The visible hours the grid reported it is drawing, or null before it has measured. */
  readonly drawnHours: number | null;
  /** Every level of the range the grid last reported, or null before it has measured. */
  readonly reportedLevels: readonly ZoomLevel[] | null;
  /** Selecting a level picked in the segment, which updates the preference `z` updates. */
  readonly onPickHours: (hours: number) => void;
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
  reportedLevels,
  onPickHours,
  hasProposal,
  sessionHref,
  onResolveNow,
  onApprove,
}: WeekActionsProps) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <p className="text-eyebrow text-text-muted">
        {blockCount} blocks · {unconfirmedReading(unconfirmedDays)}
      </p>
      {drawnHours === null || reportedLevels === null ? null : (
        <span className="flex items-center gap-2">
          <ZoomSegment levels={reportedLevels} onPick={onPickHours} pickedHours={drawnHours} />
          <KeyHint keys="z" />
        </span>
      )}
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
