/* Where the gate sends an unauthenticated request, and how it gets back.
 *
 * The return path travels in the query string rather than in router state, because signing in
 * may leave the application entirely and router state does not survive that. */

import { DEFAULT_RETURN_PATH, SIGN_IN_PATH } from "../ui/domain/shell/navigation";

const RETURN_PARAM = "next";

/* Re-exported so a caller reasoning about the return path has one import. The constant itself lives
   with the navigation table, because the landing screen is a navigation fact and the kit's top bar
   links to it too. */
export { DEFAULT_RETURN_PATH };

/* Resolved against a throwaway origin rather than inspected character by character, because the
 * question is where the browser will GO and only the browser's own parser answers that. For a
 * special scheme the URL parser strips tab and newline and normalises a backslash to a slash, so
 * `/\evil.example` and `/<tab>/evil.example` both carry an off-site authority that a `startsWith`
 * check reads as a local path. This is the same deference `css-scan.ts` pays when it ends a CSS
 * string at a newline as the browser's tokenizer does.
 *
 * The origin is a reserved TLD, so it can never resolve to anything real if one ever escapes. */
const PROBE_ORIGIN = "https://local.invalid";

/** True for a path this application can navigate to, so a crafted value cannot redirect off-site. */
function isLocalPath(value: string): boolean {
  if (!value.startsWith("/")) return false;
  try {
    return new URL(value, PROBE_ORIGIN).origin === PROBE_ORIGIN;
  } catch {
    return false;
  }
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
