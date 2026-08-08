/* WHICH MODE OF THE WEEK SCREEN A URL ASKS FOR.
 *
 * A MODE IS REACHABLE BY URL, so it survives a reload and can be linked, which is why this reads a search parameter
 * rather than component state. A tab would be state: it is which of several lists is in front, and the screen is the
 * destination either way. A mode is a way of USING the screen, and `/week?mode=session` is what makes "run the weekly
 * session" a place a reader can come back to and send to themselves.
 *
 * THE WEEK TRAVELS WITH THE MODE. The Week screen already reads its week from `?week=`, and the session is about a
 * specific week: leaving `week` out would open the session on whichever week the reader lands in, which is a different
 * week on Monday morning than it was on Sunday night. So the link carries both parameters.
 *
 * ANYTHING THAT IS NOT THE SESSION IS THE SCREEN. `?mode=weekly`, `?mode=`, a repeated parameter and a typo all land on
 * the Week screen rather than on an error: a mode a screen does not have is not a broken URL, and refusing one would
 * spend a failure surface on a query string. */

export const SESSION_MODE = "session";
export const MODE_PARAMETER = "mode";
export const WEEK_PARAMETER = "week";

/** The URL of this screen in the weekly session for one week, which is what the band's control links to. */
export function sessionPath(isoWeek: string): string {
  return `/week?${WEEK_PARAMETER}=${isoWeek}&${MODE_PARAMETER}=${SESSION_MODE}`;
}

/** The URL of the screen itself, holding the same week, which is what leaving the session links to. */
export function weekPath(isoWeek: string): string {
  return `/week?${WEEK_PARAMETER}=${isoWeek}`;
}

/** Whether the URL asks for the weekly session. */
export function isSessionMode(search: URLSearchParams): boolean {
  return search.get(MODE_PARAMETER) === SESSION_MODE;
}
