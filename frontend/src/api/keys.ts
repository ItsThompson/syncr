/* SWR cache keys.
 *
 * APPEND ONLY. One builder per resource, added at the END of this file. A mutation then
 * invalidates by naming a builder rather than by a blanket revalidation: a blanket
 * revalidation refetches the whole week when a setting changed, which is both slow and a
 * source of flicker on a surface with no animation to hide it.
 *
 * Keys are the request path, so a key read in a devtools cache entry names the resource it
 * came from without a lookup table. */

export const readinessKey = (): string => "/readyz";
export const sessionKey = (): string => "/auth/session";
