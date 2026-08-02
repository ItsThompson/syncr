/* Where the gate sends an unauthenticated request, and how it gets back.
 *
 * The return path travels in the query string rather than in router state, because signing in
 * may leave the application entirely and router state does not survive that. */

import { SIGN_IN_PATH } from "../ui/domain/shell/navigation";

const RETURN_PARAM = "next";

/** The default landing screen: where a sign-in with no recorded origin returns to. */
export const DEFAULT_RETURN_PATH = "/week";

/** True for a path this application can navigate to, so a crafted value cannot redirect off-site. */
function isLocalPath(value: string): boolean {
  return value.startsWith("/") && !value.startsWith("//");
}

export function signInTarget(requestedPath: string): string {
  const query = new URLSearchParams({ [RETURN_PARAM]: requestedPath });
  return `${SIGN_IN_PATH}?${query.toString()}`;
}

export function returnPathFrom(search: string): string {
  const requested = new URLSearchParams(search).get(RETURN_PARAM);
  if (requested === null || !isLocalPath(requested)) return DEFAULT_RETURN_PATH;
  return requested;
}
