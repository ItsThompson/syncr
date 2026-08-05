/* Which mode of the Areas screen a URL asks for.
 *
 * A MODE IS REACHABLE BY URL, so it survives a reload and can be linked, which is why this reads a search
 * parameter rather than component state. A tab would be state: it is which of several lists is in front, and
 * the screen is the destination either way. A mode is a way of USING the screen, and `?mode=review` is what
 * makes "run the pie review" a place a reader can come back to.
 *
 * ANYTHING THAT IS NOT THE REVIEW IS THE SCREEN. `?mode=weekly`, `?mode=`, a repeated parameter and a typo
 * all land on the Areas screen rather than on an error: a mode a screen does not have is not a broken URL, and
 * refusing one would spend a failure surface on a query string. */

export const REVIEW_MODE = "review";
export const MODE_PARAMETER = "mode";

/** The URL of this screen in the pie review, which is what the header's control links to. */
export const REVIEW_PATH = `/areas?${MODE_PARAMETER}=${REVIEW_MODE}`;
export const AREAS_PATH = "/areas";

/** Whether the URL asks for the pie review. */
export function isReviewMode(search: URLSearchParams): boolean {
  return search.get(MODE_PARAMETER) === REVIEW_MODE;
}
