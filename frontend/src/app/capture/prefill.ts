/* THE URL THAT OPENS CAPTURE, AND BOTH ENDS OF IT IN ONE MODULE.
 *
 * A SCREEN INVITES A CAPTURE BY NAVIGATING, and the week screen is the one that does: activating an empty slot's
 * gutter label states the slot's Area, the estimate that fits it and the window it runs in as query parameters
 * rather than calling into a dialog. That is the same seam a mode uses on this product's other screens: it
 * survives a reload and it can be linked, which a call cannot.
 *
 * ONE MODULE FOR THE WRITE AND THE READ, because a parameter renamed at one end and not the other is a flow that
 * silently stops working: the label still navigates, the Backlog still opens nothing, and every case on either
 * side of the seam stays green. Neither end spells a parameter name itself.
 *
 * THE PARAMETERS ARE CLEARED ONCE THE DIALOG IS UP, which is what keeps the seam from becoming a mode. A mode is
 * a way of using a screen and belongs in the address bar for as long as the reader is in it; an opening is one
 * act, so a reload of the URL that asked for it must not ask again.
 *
 * A PARAMETER THIS CANNOT READ IS IGNORED RATHER THAN REFUSED, which is the rule both of this product's modes
 * follow: a typo in a query string is not a broken URL, and refusing one would spend a failure surface on a
 * string. What is refused is a value that would make the form worse than an empty one -- an estimate that is not
 * a count of minutes, or half a window -- and the form then opens on its own defaults for that member alone. */

import type { CaptureOpening } from "./captureContext";
import type { CaptureWindow } from "./preferredWindow";

/* The screen a capture is authored on, spelled here as `week/session/mode.ts` spells the week's own path: a
 * screen's URL is stated by whatever composes it. */
const BACKLOG_PATH = "/backlog";

const CAPTURE_PARAMETER = "capture";
const AREA_PARAMETER = "area";
const ESTIMATE_PARAMETER = "estimate";
const FROM_PARAMETER = "from";
const TO_PARAMETER = "to";

/* What `capture` has to hold to be an ask. An exact value rather than presence, so `?capture=0` is not an
 * invitation and neither is a parameter that arrived from somewhere else meaning something else. */
const ASKED = "1";

/** Every parameter this seam owns, which is the set that goes once the dialog is open. */
const PARAMETERS: readonly string[] = [
  CAPTURE_PARAMETER,
  AREA_PARAMETER,
  ESTIMATE_PARAMETER,
  FROM_PARAMETER,
  TO_PARAMETER,
];

/** What a screen already knows about the capture it is inviting, which an empty slot knows all of. */
export interface CaptureInvitation {
  readonly areaId: string;
  /** The work's own length in minutes: for a slot, exactly what fits it. */
  readonly estimateMinutes: number;
  readonly preferredWindow: CaptureWindow;
}

/** The URL that opens capture prefilled from an invitation. */
export function capturePath(invitation: CaptureInvitation): string {
  const search = new URLSearchParams({
    [CAPTURE_PARAMETER]: ASKED,
    [AREA_PARAMETER]: invitation.areaId,
    [ESTIMATE_PARAMETER]: String(invitation.estimateMinutes),
    [FROM_PARAMETER]: invitation.preferredWindow.from,
    [TO_PARAMETER]: invitation.preferredWindow.to,
  });
  return `${BACKLOG_PATH}?${search.toString()}`;
}

/** What the URL asks capture to open with, or null when it does not ask for capture at all. */
export function capturePrefillIn(search: URLSearchParams): CaptureOpening | null {
  if (search.get(CAPTURE_PARAMETER) !== ASKED) return null;
  return {
    areaId: textIn(search, AREA_PARAMETER) ?? undefined,
    estimateMinutes: minutesIn(textIn(search, ESTIMATE_PARAMETER)) ?? undefined,
    preferredWindow:
      windowIn(textIn(search, FROM_PARAMETER), textIn(search, TO_PARAMETER)) ?? undefined,
  };
}

/** The same query with this seam's parameters removed, and everything else left as it was. */
export function withoutCapturePrefill(search: URLSearchParams): URLSearchParams {
  const left = new URLSearchParams(search);
  for (const parameter of PARAMETERS) left.delete(parameter);
  return left;
}

/** A parameter's value, or null where it is absent or empty: `?area=` names no Area. */
function textIn(search: URLSearchParams, name: string): string | null {
  const found = search.get(name);
  return found === null || found === "" ? null : found;
}

/** A count of minutes the URL states, or null when the text is not one. */
function minutesIn(text: string | null): number | null {
  if (text === null) return null;
  const minutes = Number(text);
  return Number.isInteger(minutes) && minutes > 0 ? minutes : null;
}

/**
 * The window the two instants bound, or null when it is not one.
 *
 * Both ends or neither: one instant is a moment rather than a stretch, and a preferred time needs a stretch. An
 * end at or before its start is refused for the same reason.
 */
function windowIn(from: string | null, to: string | null): CaptureWindow | null {
  if (from === null || to === null) return null;
  const begins = Date.parse(from);
  const ends = Date.parse(to);
  if (Number.isNaN(begins) || Number.isNaN(ends) || ends <= begins) return null;
  return { from, to };
}
