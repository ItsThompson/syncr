/* THE MODE HEADER. NO SERIF TITLE, which is the rule this component exists to hold.
 *
 * A page title is serif and a mode header is not, because a mode is not a destination and so does not claim the type
 * reserved for one. The header is a band carrying the mode's name in the LABEL face, an eyebrow saying the session is
 * run when the reader asks for it, and a link back to the screen.
 *
 * LEAVING IS A REAL LINK rather than a click handler that assigns a location, which is what keeps middle-click and
 * cmd-click working, and it carries the same week: a reader who leaves the session should land on the week they were
 * planning rather than on whichever week today falls in.
 *
 * THE RANGE IS NULLABLE BECAUSE THE HEADER DRAWS BEFORE THE PAYLOAD DOES. The session's pending and failed states are
 * inside the mode, not on the screen, so they take this header rather than the screen's serif band: a mode may not claim
 * a destination's type even for the second the payload is in flight. With no week read yet there is no range to state,
 * and `null` says so rather than an empty string that would leave a stray separator.
 *
 * NOTHING SCHEDULES THE SESSION AND NOTHING NAGS. The eyebrow says so in words, because a surface that is only ever
 * reached deliberately has no other way to tell a reader that it will not come looking for them. */

import { Link } from "react-router";

import { weekPath } from "../mode";

export interface SessionHeaderProps {
  readonly isoWeek: string;
  /** The week's own dates, or null before the week has been read. */
  readonly range: string | null;
}

export function SessionHeader({ isoWeek, range }: SessionHeaderProps) {
  return (
    /* Deliberately not an h1 and deliberately not serif: see the module note. */
    <div className="flex flex-wrap items-center gap-3.25 border-b border-rule-strong bg-paper-raised px-3.75 py-2">
      <b className="text-label tracking-label uppercase text-ink-deep">Weekly session</b>
      <span className="text-eyebrow text-text-muted">
        Planning {isoWeek}
        {range === null ? "" : ` \u00b7 ${range}`} &middot; whenever you ask, and syncr never asks
        for you
      </span>
      <Link className="ml-auto text-sm underline" to={weekPath(isoWeek)}>
        Leave the session
      </Link>
    </div>
  );
}
